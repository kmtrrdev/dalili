import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';
import 'landmark_screen.dart';
import 'pilgrimage_screen.dart';
import 'wizard_screen.dart';

const _vibes = [
  ('beach', '🏖️', ['beach', 'relax'], null),
  ('city', '🏙️', ['culture', 'food', 'shopping'], null),
  ('history', '🏛️', ['history', 'culture'], null),
  ('honeymoon', '💍', ['relax', 'beach', 'food'], 'honeymoon'),
  ('family', '👨‍👩‍👧', ['nature', 'beach'], 'family'),
  ('snow', '⛷️', ['ski', 'nature'], null),
];

// name shown, Wikipedia page with a real photo, country
const _dests = [
  ('Istanbul', 'Istanbul', 'Türkiye'), ('Paris', 'Paris', 'France'), ('Rome', 'Rome', 'Italy'),
  ('Dubai', 'Dubai', 'UAE'), ('Santorini', 'Oia,_Greece', 'Greece'), ('Barcelona', 'Barcelona', 'Spain'),
  ('Marrakesh', 'Marrakesh', 'Morocco'), ('Maldives', 'Tourism_in_the_Maldives', 'Maldives'), ('Tokyo', 'Tokyo', 'Japan'),
  ('Sharm El Sheikh', 'Sharm_El_Sheikh', 'Egypt'),
];

/// Home: the boarding pass to start a trip, the side doors (camera, Hajj & Umrah, events, the quick form), the trip
/// in progress, suggestions on a departures board, vibes and postcards of popular places.
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.state});
  final AppState state;

  void _wizard(BuildContext context, WizardPrefill p) =>
      Navigator.of(context).push(passRoute(WizardScreen(state: state, prefill: p)));

  @override
  Widget build(BuildContext context) {
    final items = ((state.recs?['items'] as List?) ?? []).cast<Map<String, dynamic>>();
    return RefreshIndicator(
      onRefresh: state.refreshHome,
      edgeOffset: MediaQuery.paddingOf(context).top,
      child: CustomScrollView(slivers: [
        SliverSafeArea(bottom: false, sliver: SliverToBoxAdapter(child: _TopBar(state: state))),
        SliverToBoxAdapter(
          child: Reveal(child: _HeroPass(state: state, onForm: () => _wizard(context, const WizardPrefill()))),
        ),
        SliverToBoxAdapter(
          child: Reveal(delay: const Duration(milliseconds: 120), child: _Doors(state: state, onForm: () => _wizard(context, const WizardPrefill()))),
        ),
        if (state.plan != null)
          SliverToBoxAdapter(child: Reveal(delay: const Duration(milliseconds: 200), child: _ContinuePass(state: state))),
        SliverToBoxAdapter(
          child: Reveal(
            delay: const Duration(milliseconds: 260),
            child: _DeparturesBoard(
              recs: items,
              onPick: (rec) => _showRec(context, rec),
              onPopular: (name) {
                state.logActivity('view', name);
                _wizard(context, WizardPrefill(stops: [name]));
              },
            ),
          ),
        ),
        SliverToBoxAdapter(child: _Heading(tr('vibes'), tr('vibesSub'))),
        SliverToBoxAdapter(
          child: SizedBox(
            height: 92,
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 18),
              scrollDirection: Axis.horizontal,
              itemCount: _vibes.length,
              separatorBuilder: (_, _) => const SizedBox(width: 10),
              itemBuilder: (_, i) {
                final v = _vibes[i];
                return _VibePass(
                  group: String.fromCharCode(65 + i),
                  emoji: v.$2,
                  label: tr('vibe.${v.$1}'),
                  onTap: () => _wizard(context, WizardPrefill(suggest: true, interests: v.$3, occasion: v.$4)),
                );
              },
            ),
          ),
        ),
        SliverToBoxAdapter(child: _Heading(tr('popular'), null)),
        SliverToBoxAdapter(
          child: _Postcards(onTap: (name) {
            state.logActivity('view', name);
            _wizard(context, WizardPrefill(stops: [name]));
          }),
        ),
        SliverToBoxAdapter(child: SizedBox(height: context.dockSpace + 8)),
      ]),
    );
  }

  void _showRec(BuildContext context, Map<String, dynamic> rec) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheet) => _RecSheet(
        rec: rec,
        onPlan: (city) {
          Navigator.pop(sheet);
          state.logActivity('like', city);
          _wizard(context, WizardPrefill(stops: [city]));
        },
        onDismiss: (city) {
          Navigator.pop(sheet);
          state.logActivity('dismiss', city);
          toast(context, tr('dismissed', [city]), action: tr('undo'), onAction: () => state.undoDismiss(city));
          Future.delayed(const Duration(milliseconds: 300), state.refreshHome);
        },
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final u = state.user;
    final first = u == null ? null : (u['name'] as String).trim().split(' ').first;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 10, 16, 4),
      child: Row(children: [
        Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(gradient: DC.brand, borderRadius: BorderRadius.circular(14),
              boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .35), blurRadius: 16)]),
          child: Transform.rotate(angle: isArabic ? -math.pi / 4 : math.pi / 4, child: const Icon(Icons.flight_rounded, color: DC.onBrand, size: 22)),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(first != null ? tr('hello', [first]) : tr('helloGuest'), style: TextStyle(color: context.muted, fontSize: 13)),
            Text(tr('appName'), style: display(size: 22, color: context.ink, height: 1.1)),
          ]),
        ),
        Pressable(
          onTap: () => state.goTab(Tabs.me),
          child: Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: u != null ? const SweepGradient(colors: [DC.teal, DC.violet, DC.amber, DC.teal]) : null,
              color: u == null ? context.card : null,
              border: u == null ? Border.all(color: context.line) : null,
            ),
            alignment: Alignment.center,
            child: u != null
                ? Text(first!.characters.first.toUpperCase(),
                    style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 18, color: Color(0xFF06101C)))
                : Icon(Icons.badge_outlined, color: context.muted),
          ),
        ),
      ]),
    );
  }
}

/// The hero: a blank boarding pass - "Where to next?" - whose destination line is where you type. Tilt it with your
/// finger; the plane button takes off when you send.
class _HeroPass extends StatefulWidget {
  const _HeroPass({required this.state, required this.onForm});
  final AppState state;
  final VoidCallback onForm;

  @override
  State<_HeroPass> createState() => _HeroPassState();
}

class _HeroPassState extends State<_HeroPass> with SingleTickerProviderStateMixin {
  final _c = TextEditingController();
  late final AnimationController _takeoff = AnimationController(vsync: this, duration: const Duration(milliseconds: 700));

  @override
  void dispose() {
    _c.dispose();
    _takeoff.dispose();
    super.dispose();
  }

  Future<void> _go() async {
    final text = _c.text.trim();
    final st = widget.state;
    if (text.isEmpty) {
      st.goTab(Tabs.chat);
      return;
    }
    if (st.busy) {
      toast(context, tr('busyWait')); // the text stays in the box
      return;
    }
    HapticFeedback.mediumImpact();
    FocusScope.of(context).unfocus();
    await _takeoff.forward(from: 0);
    _c.clear();
    _takeoff.value = 0;
    st.goTab(Tabs.chat);
    st.send(text);
  }

  @override
  Widget build(BuildContext context) {
    final home = (widget.state.user?['prefs'] as Map?)?['home_city'] as String?;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
      child: Tilt3D(
        maxAngle: .12,
        child: Ticket(
          gradient: context.dark
              ? const LinearGradient(colors: [Color(0xFF12223A), Color(0xFF151A3A), Color(0xFF221A3C)],
                  begin: Alignment.topLeft, end: Alignment.bottomRight)
              : const LinearGradient(colors: [Color(0xFFFFFCF5), Color(0xFFF2FBF9), Color(0xFFFFF4E6)],
                  begin: Alignment.topLeft, end: Alignment.bottomRight),
          main: Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text(L('BOARDING PASS', 'بطاقة صعود'),
                    style: mono(size: 11, color: DC.teal, spacing: 2, weight: FontWeight.w800)),
                const Spacer(),
                Text('DLL · 2026', style: mono(size: 11, color: context.faint, spacing: 1.5)),
              ]),
              const SizedBox(height: 12),
              ShaderMask(
                shaderCallback: (r) => (context.dark ? DC.brand : const LinearGradient(colors: [Color(0xFF0B7F74), Color(0xFF2266C4)])).createShader(r),
                child: Text(tr('whereTo'), style: display(size: 32, color: Colors.white, height: 1.1)),
              ),
              const SizedBox(height: 16),
              Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                PassField(L('From', 'من'), (home == null || home.isEmpty) ? '···' : home),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: AnimatedBuilder(
                      animation: _takeoff,
                      builder: (_, _) => _MiniRoute(progress: .5 + _takeoff.value * .5),
                    ),
                  ),
                ),
                PassField(L('To', 'إلى'), L('Anywhere', 'أي مكان'), end: true, valueColor: DC.teal),
              ]),
              const SizedBox(height: 14),
              Container(
                decoration: BoxDecoration(
                  color: context.dark ? Colors.white.withValues(alpha: .05) : Colors.white,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: context.line),
                ),
                padding: const EdgeInsetsDirectional.fromSTEB(14, 4, 6, 4),
                child: Row(children: [
                  Expanded(
                    child: TextField(
                      controller: _c,
                      minLines: 1,
                      maxLines: 4, // a long request wraps and stays readable
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _go(),
                      decoration: InputDecoration(
                        hintText: tr('askPh'),
                        filled: false,
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        contentPadding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                    ),
                  ),
                  _TakeoffButton(anim: _takeoff, onTap: _go),
                ]),
              ),
            ]),
          ),
          stub: Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
            child: Column(children: [
              Row(children: [
                Expanded(child: _StubAction(icon: Icons.chat_bubble_rounded, title: tr('chatWith'), sub: tr('chatWithSub'),
                    onTap: () => widget.state.goTab(Tabs.chat))),
                const SizedBox(width: 10),
                Expanded(child: _StubAction(icon: Icons.edit_note_rounded, title: tr('quickForm'), sub: tr('quickFormSub'), onTap: widget.onForm)),
              ]),
              const SizedBox(height: 12),
              Opacity(opacity: .55, child: Barcode('DALILI-${widget.state.tripId ?? 'NEW'}', height: 26)),
            ]),
          ),
        ),
      ),
    );
  }
}

class _MiniRoute extends StatelessWidget {
  const _MiniRoute({required this.progress});
  final double progress;

  @override
  Widget build(BuildContext context) {
    final rtl = Directionality.of(context) == TextDirection.rtl;
    return SizedBox(
      height: 26,
      child: LayoutBuilder(builder: (context, c) {
        final x = c.maxWidth * progress.clamp(0, 1);
        return Stack(clipBehavior: Clip.none, children: [
          Positioned.fill(
            child: CustomPaint(painter: _DashPainter(context.dark ? Colors.white24 : const Color(0x441C3460))),
          ),
          PositionedDirectional(
            start: x - 11,
            top: 1,
            child: Transform.rotate(
              angle: rtl ? -math.pi / 2 : math.pi / 2,
              child: const Icon(Icons.flight_rounded, color: DC.teal, size: 22),
            ),
          ),
        ]);
      }),
    );
  }
}

class _DashPainter extends CustomPainter {
  _DashPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..strokeWidth = 1.6
      ..strokeCap = StrokeCap.round;
    final y = size.height / 2;
    for (var x = 0.0; x < size.width; x += 8) {
      canvas.drawLine(Offset(x, y), Offset(math.min(x + 4, size.width), y), p);
    }
  }

  @override
  bool shouldRepaint(_DashPainter old) => old.color != color;
}

/// The send button: a plane that climbs away when you send.
class _TakeoffButton extends StatelessWidget {
  const _TakeoffButton({required this.anim, required this.onTap});
  final Animation<double> anim;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: tr('chatWith'),
        child: Pressable(
          onTap: onTap,
          child: Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              gradient: DC.brand,
              borderRadius: BorderRadius.circular(15),
              boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .35), blurRadius: 14, offset: const Offset(0, 5))],
            ),
            clipBehavior: Clip.antiAlias,
            child: AnimatedBuilder(
              animation: anim,
              builder: (_, _) {
                final v = Curves.easeInCubic.transform(anim.value);
                final dir = isArabic ? -1.0 : 1.0;
                return Transform.translate(
                  offset: Offset(dir * v * 40, -v * 40),
                  child: Transform.rotate(angle: dir * math.pi / 4, child: const Icon(Icons.flight_rounded, color: DC.onBrand, size: 24)),
                );
              },
            ),
          ),
        ),
      );
}

class _StubAction extends StatelessWidget {
  const _StubAction({required this.icon, required this.title, required this.sub, required this.onTap});
  final IconData icon;
  final String title, sub;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: context.dark ? Colors.white.withValues(alpha: .04) : const Color(0xFFF6F2E8),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: context.line),
          ),
          child: Row(children: [
            Icon(icon, color: DC.teal, size: 22),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
                Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 11)),
              ]),
            ),
          ]),
        ),
      );
}

/// The side doors: four 3D tiles.
class _Doors extends StatelessWidget {
  const _Doors({required this.state, required this.onForm});
  final AppState state;
  final VoidCallback onForm;

  @override
  Widget build(BuildContext context) {
    final doors = [
      ('📷', L('What\'s this place?', 'إيه المكان ده؟'), DC.sky, () => Navigator.of(context).push(passRoute(LandmarkScreen(state: state)))),
      ('🕋', L('Hajj & Umrah', 'الحج والعمرة'), const Color(0xFFC9A84A), () => Navigator.of(context).push(passRoute(PilgrimageScreen(state: state)))),
      ('🎟️', L('Big events', 'إيفنتات عالمية'), DC.amber, () => state.goTab(Tabs.events)),
      ('🧭', tr('quickForm'), DC.violet, onForm),
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Row(children: [
        for (var i = 0; i < doors.length; i++) ...[
          if (i > 0) const SizedBox(width: 10),
          Expanded(
            child: Reveal(
              delay: Duration(milliseconds: 160 + i * 70),
              child: Tilt3D(
                maxAngle: .3,
                radius: 20,
                child: Pressable(
                  onTap: doors[i].$4,
                  child: Container(
                    height: 96,
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 10),
                    decoration: BoxDecoration(
                      color: context.card,
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: doors[i].$3.withValues(alpha: .35)),
                      gradient: LinearGradient(
                        colors: [doors[i].$3.withValues(alpha: context.dark ? .18 : .14), context.card],
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                      ),
                    ),
                    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                      Text(doors[i].$1, style: const TextStyle(fontSize: 26)),
                      const SizedBox(height: 6),
                      Text(doors[i].$2, maxLines: 2, textAlign: TextAlign.center, overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, height: 1.2)),
                    ]),
                  ),
                ),
              ),
            ),
          ),
        ],
      ]),
    );
  }
}

/// The trip in progress, as a small horizontal pass.
class _ContinuePass extends StatelessWidget {
  const _ContinuePass({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final c = state.trip!['trip_contract'] as Map<String, dynamic>? ?? {};
    final stops = (c['stops'] as List?) ?? [];
    final cities = stops.isNotEmpty ? stops.map((s) => (s['ref'] as Map)['name']).toList() : [c['destination_name'] ?? c['destination']];
    final b = state.plan!['budget'] as Map<String, dynamic>?;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Pressable(
        onTap: () => state.goTab(Tabs.trip),
        child: Ticket(
          axis: Axis.horizontal,
          notch: 10,
          main: Row(children: [
            ClipRRect(
              borderRadius: const BorderRadiusDirectional.horizontal(start: Radius.circular(22)).resolve(Directionality.of(context)),
              child: SizedBox(width: 84, height: 96, child: PlacePhoto(title: '${cities.first}')),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(tr('continueTrip').toUpperCase(), style: mono(size: 10.5, color: DC.teal, spacing: 1.4)),
                  const SizedBox(height: 3),
                  Text(routeText(cities), maxLines: 1, overflow: TextOverflow.ellipsis, style: display(size: 17, color: context.ink)),
                  const SizedBox(height: 2),
                  Text('${fmtDate(c['start_date'])} – ${fmtDate(c['end_date'])}', style: TextStyle(color: context.muted, fontSize: 12)),
                ]),
              ),
            ),
          ]),
          stub: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(money(b?['total'] as num?, b?['currency'] as String?), style: display(size: 15, color: context.ink)),
              const SizedBox(height: 6),
              Icon(isArabic ? Icons.arrow_back_rounded : Icons.arrow_forward_rounded, color: DC.teal),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Suggestions on an airport departures board: split-flap city names, the match as the "gate", a live clock.
/// With no suggestions yet, the board shows popular places.
class _DeparturesBoard extends StatefulWidget {
  const _DeparturesBoard({required this.recs, required this.onPick, required this.onPopular});
  final List<Map<String, dynamic>> recs;
  final ValueChanged<Map<String, dynamic>> onPick;
  final ValueChanged<String> onPopular;

  @override
  State<_DeparturesBoard> createState() => _DeparturesBoardState();
}

class _DeparturesBoardState extends State<_DeparturesBoard> {
  late Timer _clock;
  DateTime _now = DateTime.now();

  @override
  void initState() {
    super.initState();
    _clock = Timer.periodic(const Duration(seconds: 20), (_) => setState(() => _now = DateTime.now()));
  }

  @override
  void dispose() {
    _clock.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const amber = Color(0xFFFFC56B);
    final personal = widget.recs.isNotEmpty;
    final rows = personal
        ? [for (final r in widget.recs.take(6)) (r['name'] as String, r['country'] as String? ?? '', '${r['match']}%', r)]
        : [for (final d in _dests.take(6)) (d.$1, d.$3, L('ON TIME', 'في الميعاد'), null)];
    final hh = _now.hour.toString().padLeft(2, '0'), mm = _now.minute.toString().padLeft(2, '0');
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 22, 16, 0),
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFF0B101D),
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: Colors.white.withValues(alpha: .07)),
          boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .5 : .25), blurRadius: 24, offset: const Offset(0, 10))],
        ),
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            const Icon(Icons.flight_takeoff_rounded, color: amber, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(personal ? tr('forYou') : tr('popular'), style: display(size: 17, color: Colors.white)),
                Text(personal ? tr('forYouSub') : L('Tap a flight to plan it', 'دوس على أي رحلة تخططها'),
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Color(0xFF8C98B4), fontSize: 11.5)),
              ]),
            ),
            Text('$hh:$mm', style: mono(size: 18, color: amber)),
          ]),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(flex: 6, child: Text(L('DESTINATION', 'الوجهة'), style: mono(size: 9.5, color: const Color(0xFF6E7A96), spacing: 1.2))),
            Expanded(flex: 3, child: Text(personal ? L('MATCH', 'تطابق') : L('STATUS', 'الحالة'),
                textAlign: TextAlign.end, style: mono(size: 9.5, color: const Color(0xFF6E7A96), spacing: 1.2))),
          ]),
          const Divider(color: Color(0x22FFFFFF), height: 14),
          for (var i = 0; i < rows.length; i++)
            InkWell(
              borderRadius: BorderRadius.circular(10),
              onTap: () {
                HapticFeedback.selectionClick();
                final rec = rows[i].$4;
                rec != null ? widget.onPick(rec) : widget.onPopular(rows[i].$1);
              },
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 7),
                child: Row(children: [
                  Expanded(
                    flex: 6,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: AlignmentDirectional.centerStart,
                        child: Directionality(
                          textDirection: TextDirection.ltr,
                          child: SplitFlap(
                            _boardText(rows[i].$1),
                            delay: Duration(milliseconds: 300 + i * 140),
                            style: mono(size: 15, color: Colors.white, weight: FontWeight.w800),
                            tileColor: const Color(0xFF161D2E),
                          ),
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(rows[i].$2, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Color(0xFF8C98B4), fontSize: 11)),
                    ]),
                  ),
                  Expanded(
                    flex: 3,
                    child: Text(rows[i].$3, textAlign: TextAlign.end,
                        style: personal ? mono(size: 16, color: amber) : mono(size: 11, color: DC.green, spacing: .8)),
                  ),
                ]),
              ),
            ),
        ]),
      ),
    );
  }

  /// Board text: Latin capitals, at most 12 letters (the board's width).
  static String _boardText(String name) {
    final up = name.toUpperCase();
    return up.length > 12 ? '${up.substring(0, 11)}.' : up;
  }
}

class _Heading extends StatelessWidget {
  const _Heading(this.title, this.sub);
  final String title;
  final String? sub;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 26, 20, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: display(size: 20, color: context.ink)),
          if (sub != null) Text(sub!, style: TextStyle(color: context.muted, fontSize: 13)),
        ]),
      );
}

/// A vibe as a small boarding-group pass ("GROUP A").
class _VibePass extends StatelessWidget {
  const _VibePass({required this.group, required this.emoji, required this.label, required this.onTap});
  final String group, emoji, label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: SizedBox(
          width: 190,
          child: Ticket(
            axis: Axis.horizontal,
            notch: 9,
            gap: 16,
            elevation: 4,
            main: Padding(
              padding: const EdgeInsetsDirectional.fromSTEB(14, 12, 6, 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
                Text('${L('GROUP', 'مجموعة')} $group', style: mono(size: 9.5, color: context.faint, spacing: 1.2)),
                const SizedBox(height: 4),
                Text(label, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5, height: 1.2)),
              ]),
            ),
            stub: SizedBox(width: 50, child: Center(child: Text(emoji, style: const TextStyle(fontSize: 24)))),
          ),
        ),
      );
}

/// Popular places as postcards in a 3D coverflow, each with a round stamp.
class _Postcards extends StatefulWidget {
  const _Postcards({required this.onTap});
  final ValueChanged<String> onTap;

  @override
  State<_Postcards> createState() => _PostcardsState();
}

class _PostcardsState extends State<_Postcards> {
  final _page = PageController(viewportFraction: .7);

  @override
  void dispose() {
    _page.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 250,
        child: PageView.builder(
          controller: _page,
          itemCount: _dests.length,
          padEnds: true,
          itemBuilder: (_, i) {
            final (name, wiki, country) = _dests[i];
            return Coverflow(
              controller: _page,
              index: i,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 8),
                child: Pressable(
                  onTap: () => widget.onTap(name),
                  child: Container(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(22),
                      boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .5 : .18), blurRadius: 18, offset: const Offset(0, 8))],
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: Stack(fit: StackFit.expand, children: [
                      PlacePhoto(title: wiki),
                      const DecoratedBox(
                        decoration: BoxDecoration(
                          gradient: LinearGradient(colors: [Colors.transparent, Color(0xD0000000)], begin: Alignment.center, end: Alignment.bottomCenter),
                        ),
                      ),
                      PositionedDirectional(
                        top: 10,
                        end: 10,
                        child: Stamp(label: country, center: name.characters.first, color: Colors.white.withValues(alpha: .9), size: 62),
                      ),
                      PositionedDirectional(
                        start: 16,
                        end: 16,
                        bottom: 14,
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(L('GREETINGS FROM', 'تحياتي من'), style: mono(size: 9.5, color: Colors.white70, spacing: 1.5)),
                          Text(name, style: display(size: 24, color: Colors.white)),
                        ]),
                      ),
                    ]),
                  ),
                ),
              ),
            );
          },
        ),
      );
}

/// A suggestion opened from the board: photo, why it fits, tags - plan it or hide it.
class _RecSheet extends StatelessWidget {
  const _RecSheet({required this.rec, required this.onPlan, required this.onDismiss});
  final Map<String, dynamic> rec;
  final ValueChanged<String> onPlan;
  final ValueChanged<String> onDismiss;

  String _reason() {
    final r = rec['reason'] as Map<String, dynamic>?;
    if (r == null) return '';
    final type = r['type'] as String;
    return type == 'interest' ? tr('because.interest', [tr('int.${r['interest']}')]) : tr('because.$type', [r['city']]);
  }

  @override
  Widget build(BuildContext context) {
    final tags = ((rec['tags'] as List?) ?? []).cast<String>();
    final tint = tags.isEmpty ? DC.teal : (DC.tag[tags.first] ?? DC.teal);
    final name = rec['name'] as String;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(22),
            child: SizedBox(
              height: 180,
              child: Stack(fit: StackFit.expand, children: [
                PlacePhoto(url: rec['image'] as String?, title: rec['image'] == null ? name : null,
                    emoji: tags.isEmpty ? '✈️' : (DC.emoji[tags.first] ?? '✈️'), tint: tint),
                PositionedDirectional(
                  top: 12,
                  start: 12,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(color: const Color(0xC8060C18), borderRadius: BorderRadius.circular(999),
                        border: Border.all(color: tint.withValues(alpha: .8))),
                    child: Text(tr('match', [rec['match']]), style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w800)),
                  ),
                ),
              ]),
            ),
          ),
          const SizedBox(height: 14),
          Text(name, style: display(size: 24, color: context.ink)),
          Text(rec['country'] as String? ?? '', style: TextStyle(color: context.muted)),
          const SizedBox(height: 10),
          if (_reason().isNotEmpty) Text('✨ ${_reason()}', style: const TextStyle(fontSize: 14, height: 1.35)),
          const SizedBox(height: 10),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final t in tags.take(3)) Pill('${DC.emoji[t] ?? ''} ${tr('int.$t')}', color: DC.tag[t]),
          ]),
          if ((rec['keywords'] as List?)?.isNotEmpty ?? false) ...[
            const SizedBox(height: 8),
            Text('${tr('knownFor')}: ${(rec['keywords'] as List).join(' · ')}', style: TextStyle(color: context.faint, fontSize: 12)),
          ],
          const SizedBox(height: 18),
          Row(children: [
            OutlinedButton(onPressed: () => onDismiss(name), child: Text(tr('notForMe'))),
            const SizedBox(width: 10),
            Expanded(child: BrandButton(label: tr('planThis'), icon: Icons.flight_takeoff_rounded, onTap: () => onPlan(name))),
          ]),
        ]),
      ),
    );
  }
}
