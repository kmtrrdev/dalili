import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:image_picker/image_picker.dart';
import 'package:latlong2/latlong.dart' show LatLng;

import '../core/api.dart';
import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';
import 'events_screen.dart' show TicketButton, countryName, flagOf;

/// The photo's media type from its first bytes (the picker hands back JPEG when it resizes, but a PNG or WebP that
/// was already small can come through as it is).
String imageMime(Uint8List b) {
  if (b.length > 4 && b[0] == 0x89 && b[1] == 0x50 && b[2] == 0x4E && b[3] == 0x47) return 'image/png';
  if (b.length > 12 && b[0] == 0x52 && b[1] == 0x49 && b[8] == 0x57 && b[9] == 0x45 && b[10] == 0x42 && b[11] == 0x50) {
    return 'image/webp';
  }
  return 'image/jpeg';
}

/// "30.0444°N  31.2357°E"
String coordText(num lat, num lon) =>
    '${lat.abs().toStringAsFixed(4)}°${lat >= 0 ? 'N' : 'S'}  ${lon.abs().toStringAsFixed(4)}°${lon >= 0 ? 'E' : 'W'}';

enum _Phase { pick, scanning, result, failed }

/// The landmark camera: a photo -> the place it shows (checked against Wikipedia on the server) -> a guide written
/// from its article, which the traveller can question -> "plan a trip here". The photo is only read, never stored.
class LandmarkScreen extends StatefulWidget {
  const LandmarkScreen({super.key, required this.state, @visibleForTesting this.debugResult});
  final AppState state;

  /// Opens straight on a result (an /identify answer plus the photo) - for layout tests.
  final (Map<String, dynamic>, Uint8List)? debugResult;

  @override
  State<LandmarkScreen> createState() => _LandmarkScreenState();
}

class _LandmarkScreenState extends State<LandmarkScreen> {
  static const _slow = Duration(seconds: 90); // recognition + a guide written from the article: 10-30 s, sometimes more

  _Phase _phase = _Phase.pick;
  Uint8List? _photo;
  Map<String, dynamic>? _place;
  String _fail = '';
  bool _canRetry = false; // a network / busy failure: the same photo can be sent again
  int _step = 0;
  Timer? _stepTimer;
  int _run = 0; // a newer photo retires the answer to an older one

  // the Q&A
  final _qa = <(String, String)>[]; // (role, text) as shown
  final _history = <Map<String, String>>[]; // what /ask is given (answered turns only)
  List<String> _chips = [];
  bool _asking = false;
  final _field = TextEditingController();
  final _scroll = ScrollController();

  AppState get _s => widget.state;

  @override
  void initState() {
    super.initState();
    final r = widget.debugResult;
    if (r != null) {
      _place = r.$1;
      _photo = r.$2;
      _phase = _Phase.result;
      final g = r.$1['guide'];
      _chips = g is Map ? [for (final q in (g['questions'] as List? ?? [])) '$q'] : [];
    }
  }

  @override
  void dispose() {
    _stepTimer?.cancel();
    _field.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _pick(ImageSource src) async {
    XFile? f;
    try {
      f = await ImagePicker().pickImage(source: src, maxWidth: 1280, maxHeight: 1280, imageQuality: 82);
    } catch (_) {
      if (mounted) {
        toast(
          context,
          src == ImageSource.camera
              ? L("Couldn't open the camera.", 'معرفتش أفتح الكاميرا.')
              : L("Couldn't open your photos.", 'معرفتش أفتح الصور.'),
        );
      }
      return;
    }
    if (f == null) return;
    final bytes = await f.readAsBytes();
    if (mounted) _identify(bytes);
  }

  Future<void> _identify(Uint8List bytes) async {
    final run = ++_run;
    setState(() {
      _photo = bytes;
      _phase = _Phase.scanning;
      _step = 0;
      _place = null;
      _qa.clear();
      _history.clear();
      _chips = [];
      _asking = false;
    });
    _stepTimer?.cancel();
    _stepTimer = Timer.periodic(const Duration(milliseconds: 4500), (_) {
      if (mounted && _step < 2) setState(() => _step++);
    });
    String? why;
    var retry = false;
    Map<String, dynamic>? out;
    final image = 'data:${imageMime(bytes)};base64,${base64Encode(bytes)}';
    if (image.length > 2990000) {
      why = _errPhoto; // the server takes up to ~3 MB
    } else {
      try {
        out = await _s.api.post('/api/landmarks/identify', {'image': image, 'lang': _s.lang}, _slow) as Map<String, dynamic>;
      } on ApiException catch (e) {
        retry = e.status == 0 || e.status == 429 || e.status >= 500;
        why = e.status == 429
            ? tr('errRate', [60])
            : e.status == 0
            ? tr('errNet')
            : e.status == 422 || e.status == 413
            ? _errPhoto
            : _unavailable;
      } catch (_) {
        why = _unavailable;
        retry = true;
      }
    }
    _stepTimer?.cancel();
    if (!mounted || run != _run) return;
    if (why == null && out?['found'] != true) {
      switch (out?['reason']) {
        case 'unclear':
          why = L(
            "I couldn't recognise a landmark in this photo. Try a clearer shot of the whole place, in daylight if you can.",
            'معرفتش أتعرّف على معلم في الصورة دي. جرّب صورة أوضح للمكان كله، في النور لو تقدر.',
          );
        case 'unverified':
          final g = '${out?['guess'] ?? ''}';
          why = L(
            "It may be $g, but I couldn't confirm it - so I won't guess. Try another angle.",
            'ممكن يكون $g، بس معرفتش أتأكد - فمش هخمّن. جرّب من زاوية تانية.',
          );
        default:
          why = _unavailable;
          retry = true;
      }
    }
    setState(() {
      if (why != null) {
        _phase = _Phase.failed;
        _fail = why;
        _canRetry = retry;
      } else {
        _place = out;
        _phase = _Phase.result;
        final g = out!['guide'];
        _chips = g is Map ? [for (final q in (g['questions'] as List? ?? [])) '$q'] : [];
      }
    });
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  String get _errPhoto => L("Couldn't read this photo. Try another one.", 'معرفتش أقرا الصورة دي. جرّب صورة تانية.');
  String get _unavailable => L(
    "Recognition isn't available right now. Please try again in a moment.",
    'التعرّف على الصور مش متاح دلوقتي. جرّب كمان شوية.',
  );

  Future<void> _ask(String question) async {
    final q = question.trim();
    if (q.isEmpty || _asking || _place == null) return;
    final run = _run;
    setState(() {
      _qa.add(('user', q));
      _asking = true;
    });
    _field.clear();
    _toEnd();
    String answer;
    var follow = <String>[];
    try {
      final r = await _s.api.post('/api/landmarks/ask', {
        'title': _place!['name'],
        'question': q,
        'history': _history.length > 12 ? _history.sublist(_history.length - 12) : _history,
        'lang': _s.lang,
      }, _slow) as Map<String, dynamic>;
      answer = '${r['answer'] ?? ''}';
      follow = [for (final x in (r['follow_ups'] as List? ?? [])) '$x'];
      _history
        ..add({'role': 'user', 'text': q})
        ..add({'role': 'assistant', 'text': answer});
    } on ApiException catch (e) {
      answer = e.status == 429
          ? tr('errRate', [60])
          : e.status == 0
          ? tr('errNet')
          : _guideDown;
    } catch (_) {
      answer = _guideDown;
    }
    if (!mounted || run != _run) return;
    setState(() {
      _qa.add(('assistant', answer));
      _asking = false;
      if (follow.isNotEmpty) _chips = follow;
    });
    _toEnd();
  }

  String get _guideDown =>
      L("The guide can't answer right now. Please try again in a moment.", 'الدليل مش قادر يرد دلوقتي. جرّب كمان شوية.');

  void _toEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (_scroll.hasClients) {
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 380),
        curve: Curves.easeOutCubic,
      );
    }
  });

  String get _name {
    final p = _place!;
    final g = p['guide'];
    final gn = g is Map ? '${g['name'] ?? ''}' : '';
    if (gn.isNotEmpty) return gn;
    final ar = '${p['name_ar'] ?? ''}';
    return isArabic && ar.isNotEmpty ? ar : '${p['name'] ?? ''}';
  }

  String get _where {
    final p = _place!;
    final city = '${p['city'] ?? ''}', country = countryName('${p['country_code'] ?? ''}');
    return [city, country].where((x) => x.isNotEmpty).join(isArabic ? '، ' : ', ');
  }

  void _planHere() {
    if (_s.busy) {
      toast(context, tr('busyWait'));
      return;
    }
    final msg = isArabic ? 'عايز أسافر $_where - نفسي أشوف $_name' : 'Plan a trip to $_where - I want to see $_name';
    unawaited(_s.send(msg));
    _s.goTab(Tabs.chat);
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    extendBodyBehindAppBar: true,
    backgroundColor: context.dark ? DC.night : DC.day,
    appBar: AppBar(
      title: Text(L('Landmark camera', 'كاميرا المعالم')),
      actions: [
        if (_phase == _Phase.result)
          IconButton(
            tooltip: L('Another photo', 'صورة تانية'),
            onPressed: () => setState(() => _phase = _Phase.pick),
            icon: const Text('📷', style: TextStyle(fontSize: 20)),
          ),
      ],
    ),
    body: SkyBackground(
      planes: 2,
      child: Builder(
        builder: (context) {
          final pad = MediaQuery.paddingOf(context);
          return AnimatedSwitcher(
            duration: const Duration(milliseconds: 480),
            switchInCurve: Curves.easeOutCubic,
            switchOutCurve: Curves.easeInCubic,
            transitionBuilder: (child, a) => FadeTransition(
              opacity: a,
              child: AnimatedBuilder(
                animation: a,
                builder: (_, c) => Transform(
                  alignment: Alignment.center,
                  transform: perspective()
                    ..translateByDouble(0, (1 - a.value) * 30, 0, 1)
                    ..rotateX((1 - a.value) * .25),
                  child: c,
                ),
                child: child,
              ),
            ),
            child: KeyedSubtree(
              key: ValueKey(_phase),
              child: switch (_phase) {
                _Phase.pick => _PickView(pad: pad, onPick: _pick),
                _Phase.scanning => _ScanView(pad: pad, photo: _photo!, step: _step),
                _Phase.failed => _FailView(
                  pad: pad,
                  photo: _photo,
                  text: _fail,
                  onRetry: _canRetry && _photo != null ? () => _identify(_photo!) : null,
                  onPick: _pick,
                ),
                _Phase.result => _result(context, pad),
              },
            ),
          );
        },
      ),
    ),
  );

  // ---------------------------------------------------------------- the result: postcard + guide pass + Q&A
  Widget _result(BuildContext context, EdgeInsets pad) {
    final p = _place!;
    final g = p['guide'] is Map ? p['guide'] as Map : const {};
    final conf = '${p['confidence'] ?? 'low'}';
    final summary = '${g['summary'] ?? ''}';
    final history = [for (final x in (g['history'] as List? ?? [])) '$x'];
    final tips = [for (final x in (g['tips'] as List? ?? [])) '$x'];
    final alts = [for (final x in (p['alternatives'] as List? ?? [])) '$x'];
    final wiki = '${p['wikipedia'] ?? ''}';
    final lat = p['lat'] as num?, lon = p['lon'] as num?;
    final seen = '${p['seen'] ?? ''}';
    final confColor = conf == 'high'
        ? DC.green
        : conf == 'medium'
        ? DC.sky
        : DC.amber;
    final confLabel = switch (conf) {
      'high' => L('Recognised', 'اتعرّفت عليه'),
      'medium' => L('Probably', 'غالباً'),
      _ => L('Best guess', 'أقرب تخمين'),
    };
    return ListView(
      controller: _scroll,
      padding: EdgeInsets.fromLTRB(16, pad.top + 8, 16, pad.bottom + 24),
      children: [
        Reveal(
          child: _Postcard(
            photo: _photo!,
            image: '${p['image'] ?? ''}',
            name: _name,
            // Stamp letters are drawn one by one round a ring, so the stamp stays Latin (like a passport stamp).
            stamp: switch (conf) {
              'high' => 'RECOGNISED',
              'medium' => 'PROBABLY',
              _ => 'BEST GUESS',
            },
            stampMark: conf == 'high' ? '✓' : '?',
            stampColor: confColor,
          ),
        ),
        const SizedBox(height: 16),
        Reveal(
          delay: const Duration(milliseconds: 120),
          child: Ticket(
            main: Padding(
              padding: const EdgeInsets.fromLTRB(18, 18, 18, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          _name,
                          style: display(size: 24, weight: FontWeight.w700, color: context.ink, height: 1.2),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Pill(confLabel, color: confColor),
                    ],
                  ),
                  if (_where.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Text(flagOf('${p['country_code'] ?? ''}'), style: const TextStyle(fontSize: 16)),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            _where,
                            style: TextStyle(color: context.muted, fontWeight: FontWeight.w600),
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (conf != 'high') ...[
                    const SizedBox(height: 12),
                    _Honest(
                      text: conf == 'medium'
                          ? L(
                              'Probably this place - check that it matches what you saw.',
                              'غالباً هو المكان ده - اتأكد إنه زي اللي شفته.',
                            )
                          : L(
                              "My best guess - I'm not fully sure. Compare the two photos before you rely on it.",
                              'ده أقرب تخمين عندي - مش متأكد أوي. قارن الصورتين قبل ما تعتمد عليه.',
                            ),
                      seen: conf == 'low' && seen.isNotEmpty ? seen : null,
                      alternatives: alts,
                    ),
                  ],
                  if (summary.isNotEmpty) ...[const SizedBox(height: 14), MdText(summary, color: context.ink)],
                  if (history.isNotEmpty) ...[_Heading(L('History', 'تاريخه')), _Timeline(history)],
                  if (tips.isNotEmpty) ...[
                    _Heading(L('Visiting tips', 'نصايح للزيارة')),
                    for (final t in tips)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('💡', style: TextStyle(fontSize: 14)),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(t, style: TextStyle(color: context.ink, height: 1.4)),
                            ),
                          ],
                        ),
                      ),
                  ],
                  if (lat != null && lon != null) ...[
                    const SizedBox(height: 14),
                    PassField(L('Coordinates', 'الإحداثيات'), coordText(lat, lon)),
                  ],
                ],
              ),
            ),
            stub: Padding(
              padding: const EdgeInsets.fromLTRB(18, 4, 18, 18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TicketButton(label: L('Plan a trip here', 'خطّطلي رحلة هنا'), onTap: _planHere),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      if (wiki.isNotEmpty) ...[
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () => openLink(wiki),
                            icon: const Icon(Icons.open_in_new_rounded, size: 18),
                            label: Text(L('Wikipedia', 'ويكيبيديا'), maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                        ),
                        const SizedBox(width: 10),
                      ],
                      Expanded(
                        child: OutlinedButton(
                          onPressed: () => setState(() => _phase = _Phase.pick),
                          child: Text('📷  ${L('Another photo', 'صورة تانية')}', maxLines: 1, overflow: TextOverflow.ellipsis),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  Barcode('${p['name'] ?? _name}', height: 34),
                ],
              ),
            ),
          ),
        ),
        // The map sits outside the pass: a ticket paints its perforation on its own canvas, which a layered child
        // (the map's tiles) would break.
        if (lat != null && lon != null) ...[
          const SizedBox(height: 16),
          Reveal(delay: const Duration(milliseconds: 180), child: _MiniMap(lat: lat.toDouble(), lon: lon.toDouble())),
        ],
        const SizedBox(height: 16),
        Reveal(delay: const Duration(milliseconds: 220), child: _askCard(context)),
      ],
    );
  }

  Widget _askCard(BuildContext context) => Container(
    padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
    decoration: BoxDecoration(
      color: context.card.withValues(alpha: .94),
      borderRadius: BorderRadius.circular(22),
      border: Border.all(color: context.line),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Text('🧭', style: TextStyle(fontSize: 18)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(L('Ask your guide', 'اسأل الدليل'), style: display(size: 17, color: context.ink)),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          L('Answers come from the place\'s Wikipedia article.', 'الإجابات من مقالة المكان على ويكيبيديا.'),
          style: TextStyle(color: context.faint, fontSize: 12),
        ),
        const SizedBox(height: 10),
        for (final (role, text) in _qa) _Bubble(user: role == 'user', text: text),
        if (_asking) const Align(alignment: AlignmentDirectional.centerStart, child: _Typing()),
        if (_chips.isNotEmpty) ...[
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final q in _chips)
                Pressable(
                  onTap: _asking ? null : () => _ask(q),
                  child: AnimatedOpacity(
                    opacity: _asking ? .45 : 1,
                    duration: const Duration(milliseconds: 200),
                    child: Container(
                      constraints: const BoxConstraints(minHeight: 44),
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      decoration: BoxDecoration(
                        color: DC.teal.withValues(alpha: context.dark ? .14 : .12),
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(color: DC.teal.withValues(alpha: .35)),
                      ),
                      child: Text(
                        '✨ $q',
                        style: TextStyle(color: context.ink, fontSize: 13, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ],
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _field,
                maxLength: 500,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: _ask,
                decoration: InputDecoration(
                  hintText: L('Ask anything about this place…', 'اسأل أي حاجة عن المكان ده…'),
                  counterText: '',
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              tooltip: L('Send', 'ابعت'),
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _asking ? null : () => _ask(_field.text),
              icon: Icon(Icons.send_rounded, textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr),
            ),
          ],
        ),
      ],
    ),
  );
}

// ---------------------------------------------------------------- 1. choose a photo
class _PickView extends StatelessWidget {
  const _PickView({required this.pad, required this.onPick});
  final EdgeInsets pad;
  final ValueChanged<ImageSource> onPick;

  @override
  Widget build(BuildContext context) => ListView(
    padding: EdgeInsets.fromLTRB(24, pad.top + 12, 24, pad.bottom + 24),
    children: [
      Center(
        child: SizedBox(
          width: 230,
          height: 230,
          child: CustomPaint(
            painter: _Corners(color: DC.teal, inset: 0),
            child: const Center(
              child: Float(child: Text('🏛️', style: TextStyle(fontSize: 84))),
            ),
          ),
        ),
      ),
      const SizedBox(height: 26),
      Text(
        L("What's this place?", 'إيه المكان ده؟'),
        textAlign: TextAlign.center,
        style: display(size: 28, weight: FontWeight.w700, color: context.ink),
      ),
      const SizedBox(height: 8),
      Text(
        L(
          'Photograph a monument, a mosque, a bridge or a square - Dalili recognises it, tells you its story and answers your questions.',
          'صوّر أثر أو جامع أو كوبري أو ميدان - دليلي يتعرّف عليه، يحكيلك حكايته ويرد على أسئلتك.',
        ),
        textAlign: TextAlign.center,
        style: TextStyle(color: context.muted, height: 1.45),
      ),
      const SizedBox(height: 28),
      BrandButton(label: '📷  ${L('Take a photo', 'صوّر دلوقتي')}', onTap: () => onPick(ImageSource.camera)),
      const SizedBox(height: 12),
      SizedBox(
        height: 52,
        child: OutlinedButton(
          onPressed: () => onPick(ImageSource.gallery),
          child: Text('🖼️  ${L('Choose from your photos', 'اختار من صورك')}', maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
      ),
      const SizedBox(height: 18),
      Text(
        '🔒 ${L("Your photo is only read to recognise the place - it isn't stored.", 'صورتك بتتقري بس عشان نعرف المكان - مش بتتحفظ.')}',
        textAlign: TextAlign.center,
        style: TextStyle(color: context.faint, fontSize: 12.5),
      ),
    ],
  );
}

// ---------------------------------------------------------------- 2. scanning
class _ScanView extends StatelessWidget {
  const _ScanView({required this.pad, required this.photo, required this.step});
  final EdgeInsets pad;
  final Uint8List photo;
  final int step;

  @override
  Widget build(BuildContext context) {
    final steps = [
      L('Recognising…', 'بتعرّف عليه…'),
      L('Checking it with Wikipedia…', 'بتأكد منه في ويكيبيديا…'),
      L('Writing your guide…', 'بكتبلك الدليل…'),
    ];
    final h = math.min(460.0, MediaQuery.sizeOf(context).height * .56);
    return ListView(
      padding: EdgeInsets.fromLTRB(20, pad.top + 8, 20, pad.bottom + 24),
      children: [
        SizedBox(
          height: h,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(28),
            child: Stack(
              fit: StackFit.expand,
              children: [
                Image.memory(photo, fit: BoxFit.cover, gaplessPlayback: true),
                ColoredBox(color: Colors.black.withValues(alpha: .28)),
                const RepaintBoundary(child: _Scanner()),
              ],
            ),
          ),
        ),
        const SizedBox(height: 22),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.4, color: DC.teal)),
            const SizedBox(width: 12),
            Flexible(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 350),
                transitionBuilder: (c, a) => FadeTransition(
                  opacity: a,
                  child: SlideTransition(
                    position: Tween(begin: const Offset(0, .4), end: Offset.zero).animate(a),
                    child: c,
                  ),
                ),
                child: Text(
                  steps[step.clamp(0, 2)],
                  key: ValueKey(step),
                  style: display(size: 17, color: context.ink),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Text(
          L('This takes a few seconds.', 'ده بياخد كام ثانية.'),
          textAlign: TextAlign.center,
          style: TextStyle(color: context.faint, fontSize: 12.5),
        ),
      ],
    );
  }
}

/// The viewfinder over the photo: corners, a faint grid and a glowing line sweeping up and down.
class _Scanner extends StatefulWidget {
  const _Scanner();

  @override
  State<_Scanner> createState() => _ScannerState();
}

class _ScannerState extends State<_Scanner> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2200))
    ..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CustomPaint(painter: _ScanPainter(_c));
}

class _ScanPainter extends CustomPainter {
  _ScanPainter(this.t) : super(repaint: t);
  final Animation<double> t;

  @override
  void paint(Canvas canvas, Size size) {
    _Corners(color: Colors.white, inset: 18).paint(canvas, size);
    final grid = Paint()..color = Colors.white.withValues(alpha: .10);
    for (var x = size.width / 8; x < size.width; x += size.width / 8) {
      for (var y = size.height / 10; y < size.height; y += size.height / 10) {
        canvas.drawCircle(Offset(x, y), 1.1, grid);
      }
    }
    final y = 24 + (size.height - 48) * Curves.easeInOutSine.transform(t.value);
    final glow = Rect.fromLTWH(0, y - 46, size.width, 46);
    canvas.drawRect(
      glow,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [DC.teal.withValues(alpha: 0), DC.teal.withValues(alpha: .28)],
        ).createShader(glow),
    );
    canvas.drawLine(
      Offset(18, y),
      Offset(size.width - 18, y),
      Paint()
        ..color = DC.teal
        ..strokeWidth = 2.4
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(_ScanPainter old) => false;
}

/// Four viewfinder corners.
class _Corners extends CustomPainter {
  _Corners({required this.color, required this.inset});
  final Color color;
  final double inset;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..strokeWidth = 3.5
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    final r = Rect.fromLTRB(inset, inset, size.width - inset, size.height - inset);
    final l = math.min(r.width, r.height) * .16;
    for (final (o, dx, dy) in [
      (r.topLeft, 1.0, 1.0),
      (r.topRight, -1.0, 1.0),
      (r.bottomLeft, 1.0, -1.0),
      (r.bottomRight, -1.0, -1.0),
    ]) {
      canvas.drawPath(
        Path()
          ..moveTo(o.dx, o.dy + dy * l)
          ..lineTo(o.dx, o.dy)
          ..lineTo(o.dx + dx * l, o.dy),
        p,
      );
    }
  }

  @override
  bool shouldRepaint(_Corners old) => old.color != color || old.inset != inset;
}

// ---------------------------------------------------------------- 3a. not recognised / failed
class _FailView extends StatelessWidget {
  const _FailView({required this.pad, required this.photo, required this.text, required this.onRetry, required this.onPick});
  final EdgeInsets pad;
  final Uint8List? photo;
  final String text;
  final VoidCallback? onRetry;
  final ValueChanged<ImageSource> onPick;

  @override
  Widget build(BuildContext context) => ListView(
    padding: EdgeInsets.fromLTRB(20, pad.top + 8, 20, pad.bottom + 24),
    children: [
      if (photo != null)
        SizedBox(
          height: 240,
          child: Stack(
            children: [
              Positioned.fill(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(26),
                  child: ColorFiltered(
                    colorFilter: const ColorFilter.matrix([
                      .33, .33, .33, 0, 0, .33, .33, .33, 0, 0, .33, .33, .33, 0, 0, 0, 0, 0, .7, 0, //
                    ]),
                    child: Image.memory(photo!, fit: BoxFit.cover, gaplessPlayback: true),
                  ),
                ),
              ),
              const PositionedDirectional(
                end: 14,
                bottom: 14,
                child: Stamp(label: 'NOT SURE · NOT SURE ·', center: '?', color: DC.amber, size: 96),
              ),
            ],
          ),
        ),
      const SizedBox(height: 22),
      Text(
        text,
        textAlign: TextAlign.center,
        style: TextStyle(color: context.ink, fontSize: 16, height: 1.45),
      ),
      const SizedBox(height: 22),
      if (onRetry != null) ...[
        BrandButton(label: '↻  ${L('Try again', 'جرّب تاني')}', onTap: onRetry),
        const SizedBox(height: 12),
      ],
      Row(
        children: [
          Expanded(
            child: SizedBox(
              height: 50,
              child: OutlinedButton(
                onPressed: () => onPick(ImageSource.camera),
                child: Text('📷  ${L('New photo', 'صورة جديدة')}', maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: SizedBox(
              height: 50,
              child: OutlinedButton(
                onPressed: () => onPick(ImageSource.gallery),
                child: Text('🖼️  ${L('Your photos', 'صورك')}', maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ),
          ),
        ],
      ),
    ],
  );
}

// ---------------------------------------------------------------- 3b. the result's pieces
/// A postcard that turns over: the place's own photo (from Wikipedia) on the front, yours on the back.
class _Postcard extends StatelessWidget {
  const _Postcard({
    required this.photo,
    required this.image,
    required this.name,
    required this.stamp,
    required this.stampMark,
    required this.stampColor,
  });
  final Uint8List photo;
  final String image;
  final String name;
  final String stamp;
  final String stampMark;
  final Color stampColor;

  @override
  Widget build(BuildContext context) {
    const h = 250.0;
    Widget face({required Widget pic, required String caption, Widget? corner}) => SizedBox(
      height: h,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(26),
        child: Stack(
          fit: StackFit.expand,
          children: [
            pic,
            const DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.transparent, Colors.transparent, Color(0xB3000000)],
                ),
              ),
            ),
            // The postcard's white border.
            DecoratedBox(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(26),
                border: Border.all(color: Colors.white.withValues(alpha: .85), width: 5),
              ),
            ),
            PositionedDirectional(
              start: 20,
              end: 110,
              bottom: 18,
              child: Text(
                caption,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: display(size: 20, color: Colors.white, height: 1.15),
              ),
            ),
            ?corner,
          ],
        ),
      ),
    );
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Tilt3D(
          maxAngle: .1,
          radius: 26,
          child: FlipCard(
            front: face(
              pic: image.isNotEmpty
                  ? PlacePhoto(url: image, emoji: '🏛️')
                  : Image.memory(photo, fit: BoxFit.cover, gaplessPlayback: true),
              caption: name,
              corner: PositionedDirectional(
                top: 14,
                end: 14,
                child: Stamp(label: '$stamp · DALILI ·', center: stampMark, color: stampColor, size: 84),
              ),
            ),
            back: face(
              pic: Image.memory(photo, fit: BoxFit.cover, gaplessPlayback: true),
              caption: L('Your photo', 'صورتك'),
              corner: PositionedDirectional(
                top: 16,
                end: 16,
                child: Pill(L('Tap to turn back', 'دوس عشان ترجع'), color: Colors.black54, solid: true),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          '↻ ${L('Tap the postcard to compare it with your photo', 'دوس على الكارت عشان تقارنه بصورتك')}',
          textAlign: TextAlign.center,
          style: TextStyle(color: context.faint, fontSize: 12),
        ),
      ],
    );
  }
}

/// Said plainly when the recognition isn't certain.
class _Honest extends StatelessWidget {
  const _Honest({required this.text, this.seen, this.alternatives = const []});
  final String text;
  final String? seen;
  final List<String> alternatives;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: DC.amber.withValues(alpha: context.dark ? .12 : .14),
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: DC.amber.withValues(alpha: .4)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '🤔 $text',
          style: TextStyle(color: context.ink, fontSize: 13.5, height: 1.4, fontWeight: FontWeight.w600),
        ),
        if (seen != null) ...[
          const SizedBox(height: 6),
          Text(
            '${L('What I see', 'اللي شايفه')}: $seen',
            textDirection: TextDirection.ltr,
            style: TextStyle(color: context.muted, fontSize: 12.5),
          ),
        ],
        if (alternatives.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            L('Or maybe', 'أو ممكن يكون'),
            style: TextStyle(color: context.muted, fontSize: 12, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final a in alternatives)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: DC.amber.withValues(alpha: .16), borderRadius: BorderRadius.circular(12)),
                  child: Text(a, style: const TextStyle(color: DC.amber, fontSize: 12, fontWeight: FontWeight.w700)),
                ),
            ],
          ),
        ],
      ],
    ),
  );
}

class _Heading extends StatelessWidget {
  const _Heading(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 18, bottom: 10),
    child: Text(
      text.toUpperCase(),
      style: TextStyle(fontSize: 11, letterSpacing: 1.4, fontWeight: FontWeight.w800, color: context.faint),
    ),
  );
}

/// Key moments as a dotted timeline.
class _Timeline extends StatelessWidget {
  const _Timeline(this.items);
  final List<String> items;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      for (var i = 0; i < items.length; i++)
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 18,
              child: Column(
                children: [
                  Container(
                    width: 10,
                    height: 10,
                    margin: const EdgeInsets.only(top: 5),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: DC.teal,
                      boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .5), blurRadius: 6)],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Container(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(items[i], style: TextStyle(color: context.ink, height: 1.4)),
              ),
            ),
          ],
        ),
    ],
  );
}

/// A small map with a pin on the place; a tap opens it in the maps app / browser.
class _MiniMap extends StatelessWidget {
  const _MiniMap({required this.lat, required this.lon});
  final double lat;
  final double lon;

  @override
  Widget build(BuildContext context) {
    final at = LatLng(lat, lon);
    return Semantics(
      button: true,
      label: L('Open the map', 'افتح الخريطة'),
      child: Pressable(
        onTap: () => openLink('https://www.openstreetmap.org/?mlat=$lat&mlon=$lon#map=16/$lat/$lon'),
        child: SizedBox(
          height: 150,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(16),
            child: RepaintBoundary(
              child: Stack(
                children: [
                  IgnorePointer(
                    child: FlutterMap(
                      options: MapOptions(
                        initialCenter: at,
                        initialZoom: 14.5,
                        interactionOptions: const InteractionOptions(flags: InteractiveFlag.none),
                      ),
                      children: [
                        TileLayer(
                          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                          userAgentPackageName: 'com.daliliai.travelplanner',
                          tileBuilder: context.dark ? darkModeTileBuilder : null,
                        ),
                        MarkerLayer(
                          markers: [
                            Marker(
                              point: at,
                              width: 44,
                              height: 44,
                              alignment: Alignment.topCenter,
                              child: const Text('📍', style: TextStyle(fontSize: 34)),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  PositionedDirectional(
                    end: 6,
                    bottom: 4,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      color: Colors.white.withValues(alpha: .75),
                      child: const Text('© OpenStreetMap', style: TextStyle(fontSize: 9, color: Colors.black87)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.user, required this.text});
  final bool user;
  final String text;

  @override
  Widget build(BuildContext context) => Align(
    alignment: user ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
    child: ConstrainedBox(
      constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * .76),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          gradient: user ? DC.brand : null,
          color: user ? null : context.card2,
          borderRadius: BorderRadiusDirectional.only(
            topStart: const Radius.circular(18),
            topEnd: const Radius.circular(18),
            bottomStart: Radius.circular(user ? 18 : 4),
            bottomEnd: Radius.circular(user ? 4 : 18),
          ),
        ),
        child: user
            ? Text(
                text,
                style: const TextStyle(color: DC.onBrand, fontWeight: FontWeight.w600),
              )
            : MdText(text, color: context.ink, size: 14.5),
      ),
    ),
  );
}

/// Three dots while the guide writes.
class _Typing extends StatefulWidget {
  const _Typing();

  @override
  State<_Typing> createState() => _TypingState();
}

class _TypingState extends State<_Typing> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 8),
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    decoration: BoxDecoration(color: context.card2, borderRadius: BorderRadius.circular(18)),
    child: RepaintBoundary(
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < 3; i++)
              Container(
                width: 7,
                height: 7,
                margin: const EdgeInsets.symmetric(horizontal: 2.5),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: context.muted.withValues(
                    alpha: .3 + .7 * (.5 + .5 * math.sin((_c.value - i * .18) * 2 * math.pi)).clamp(0.0, 1.0),
                  ),
                ),
              ),
          ],
        ),
      ),
    ),
  );
}
