import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';
import 'landmark_screen.dart';

/// The chat with Dalili. While a plan is being made, a flight-status ticket shows the stations it has passed (a plane
/// moving along the line); the finished plan prints out as a boarding pass that opens My trip.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.state});
  final AppState state;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  int _seen = 0;
  bool _wasBusy = false;

  AppState get st => widget.state;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send([String? text]) {
    final t = (text ?? _input.text).trim();
    if (t.isEmpty) return;
    if (st.busy) {
      toast(context, tr('busyWait'));
      return;
    }
    HapticFeedback.lightImpact();
    _input.clear();
    FocusScope.of(context).unfocus(); // close the keyboard so the progress and the answer are visible
    st.send(t);
  }

  void _toBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent + 240, duration: const Duration(milliseconds: 420), curve: Curves.easeOutCubic);
      }
    });
  }

  /// Only the agents' own next-step ideas, written for this trip and this traveller (no fixed quick replies).
  List<String> get _chips {
    if (st.busy) return [];
    return ((st.trip?['metadata'] as Map?)?['suggestions'] as List?)?.cast<String>() ?? [];
  }

  @override
  Widget build(BuildContext context) {
    if (st.messages.length != _seen || st.busy != _wasBusy) {
      _seen = st.messages.length;
      _wasBusy = st.busy;
      _toBottom();
    }
    final chips = _chips;
    final keyboard = View.of(context).viewInsets.bottom > 0;
    final bottom = keyboard ? 8.0 : context.dockSpace - 8;
    return Column(children: [
      _Header(state: st),
      Expanded(
        child: ListView.builder(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 16),
          itemCount: st.messages.length + (st.busy ? 1 : 0),
          itemBuilder: (_, i) {
            if (i == st.messages.length) return _FlightStatus(progress: st.progress, hasPlan: st.plan != null);
            final m = st.messages[i];
            final last = i == st.messages.length - 1;
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              _Bubble(line: m, fresh: last),
              if (m.tripCard && st.plan != null && last)
                _PrintedPass(key: ValueKey(st.planVersion), state: st, onOpen: () => st.goTab(Tabs.trip)),
            ]);
          },
        ),
      ),
      if (chips.isNotEmpty)
        SizedBox(
          height: 46,
          child: ListView.separated(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            scrollDirection: Axis.horizontal,
            itemCount: chips.length,
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemBuilder: (_, i) => Reveal(
              delay: Duration(milliseconds: i * 70),
              offset: 12,
              child: Pressable(
                onTap: () => _send(chips[i]),
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 270),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: context.card,
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: DC.teal.withValues(alpha: .4)),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    const Icon(Icons.auto_awesome_rounded, size: 14, color: DC.teal),
                    const SizedBox(width: 6),
                    Flexible(child: Text(chips[i], maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
                  ]),
                ),
              ),
            ),
          ),
        ),
      AnimatedPadding(
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
        padding: EdgeInsets.fromLTRB(12, 8, 12, bottom),
        child: _Composer(
          controller: _input,
          busy: st.busy,
          onSend: _send,
          onCamera: () => Navigator.of(context).push(passRoute(LandmarkScreen(state: st))),
        ),
      ),
    ]);
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) => ClipRect(
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
          child: Container(
            padding: EdgeInsets.fromLTRB(16, MediaQuery.paddingOf(context).top + 8, 8, 10),
            decoration: BoxDecoration(
              color: context.dark ? const Color(0x990A1020) : Colors.white.withValues(alpha: .6),
              border: Border(bottom: BorderSide(color: context.line)),
            ),
            child: Row(children: [
              _Radar(busy: state.busy),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(tr('chatTitle'), style: display(size: 18, color: context.ink)),
                  AnimatedSwitcher(
                    duration: const Duration(milliseconds: 250),
                    child: Text(
                      state.busy ? tr('chatWorking') : tr('chatReady'),
                      key: ValueKey(state.busy),
                      style: TextStyle(fontSize: 12, color: state.busy ? DC.teal : context.muted, fontWeight: FontWeight.w600),
                    ),
                  ),
                ]),
              ),
              if (state.plan != null)
                IconButton(
                  tooltip: tr('viewTrip'),
                  onPressed: () => state.goTab(Tabs.trip),
                  icon: const Icon(Icons.confirmation_number_rounded),
                ),
              IconButton(
                tooltip: tr('newChat'),
                onPressed: state.busy ? null : state.newTrip,
                icon: const Icon(Icons.add_circle_outline_rounded),
              ),
            ]),
          ),
        ),
      );
}

/// Dalili's avatar: a radar that sweeps while it works.
class _Radar extends StatefulWidget {
  const _Radar({required this.busy});
  final bool busy;

  @override
  State<_Radar> createState() => _RadarState();
}

class _RadarState extends State<_Radar> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1800));

  @override
  void initState() {
    super.initState();
    if (widget.busy) _c.repeat();
  }

  @override
  void didUpdateWidget(_Radar old) {
    super.didUpdateWidget(old);
    if (widget.busy && !_c.isAnimating) _c.repeat();
    if (!widget.busy && _c.isAnimating) _c.stop();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 42,
        height: 42,
        child: Stack(alignment: Alignment.center, children: [
          if (widget.busy)
            AnimatedBuilder(
              animation: _c,
              builder: (_, _) => Transform.rotate(
                angle: _c.value * 2 * math.pi,
                child: Container(
                  decoration: const BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: SweepGradient(colors: [Color(0x003DE0D0), Color(0xAA3DE0D0), Color(0x003DE0D0)], stops: [0, .2, .21]),
                  ),
                ),
              ),
            ),
          Container(
            width: 34,
            height: 34,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(colors: [Color(0xFF7FF5EA), DC.teal, Color(0xFF1A6F86)], center: Alignment(-.3, -.4)),
            ),
            child: const Icon(Icons.auto_awesome_rounded, color: DC.onBrand, size: 18),
          ),
        ]),
      );
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.line, required this.fresh});
  final ChatLine line;
  final bool fresh;

  @override
  Widget build(BuildContext context) {
    final me = line.role == 'user';
    final bubble = Align(
      alignment: me ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
      child: Container(
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * .84),
        margin: const EdgeInsets.symmetric(vertical: 5),
        padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 11),
        decoration: BoxDecoration(
          gradient: me ? DC.brand : null,
          color: me ? null : context.card,
          border: me ? null : Border.all(color: context.line),
          boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .25 : .06), blurRadius: 10, offset: const Offset(0, 4))],
          borderRadius: BorderRadiusDirectional.only(
            topStart: const Radius.circular(20),
            topEnd: const Radius.circular(20),
            bottomStart: Radius.circular(me ? 20 : 6),
            bottomEnd: Radius.circular(me ? 6 : 20),
          ),
        ),
        child: MdText(line.text, color: me ? DC.onBrand : null, size: 14.5),
      ),
    );
    return fresh ? Reveal(offset: 16, child: bubble) : bubble;
  }
}

/// The planning progress as a flight status: stations along a line, a plane at the current one.
class _FlightStatus extends StatelessWidget {
  const _FlightStatus({required this.progress, required this.hasPlan});
  final Progress? progress;
  final bool hasPlan;

  static const _stations = [
    ('understand', Icons.psychology_alt_rounded),
    ('flights', Icons.flight_rounded),
    ('hotels', Icons.hotel_rounded),
    ('activities', Icons.place_rounded),
    ('plan', Icons.event_note_rounded),
    ('review', Icons.fact_check_rounded),
  ];

  @override
  Widget build(BuildContext context) {
    final seen = progress?.steps ?? const <String>[];
    final current = progress?.current ?? 'understand';
    // Places and activities are one station; weather/currency/etc. count toward the station they belong to.
    int stationOf(String s) => switch (s) {
          'understand' => 0,
          'flights' => 1,
          'hotels' => 2,
          'places' || 'activities' || 'transport' || 'weather' || 'currency' || 'knowledge' => 3,
          'plan' => 4,
          'review' => 5,
          _ => 0,
        };
    final at = seen.isEmpty ? 0 : seen.map(stationOf).reduce(math.max);
    return Align(
      alignment: AlignmentDirectional.centerStart,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 8),
        width: math.min(MediaQuery.sizeOf(context).width * .9, 380),
        child: Ticket(
          main: Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(color: DC.amber.withValues(alpha: .18), borderRadius: BorderRadius.circular(6)),
                  child: Text(L('BOARDING', 'جاري الصعود'), style: mono(size: 10, color: DC.amber, spacing: 1.2)),
                ),
                const Spacer(),
                Text(L('FLIGHT STATUS', 'حالة الرحلة'), style: mono(size: 10, color: context.faint, spacing: 1.2)),
              ]),
              const SizedBox(height: 14),
              _StationLine(at: at, stations: _stations.map((s) => s.$2).toList()),
            ]),
          ),
          stub: Padding(
            padding: const EdgeInsets.fromLTRB(16, 2, 16, 14),
            child: Row(children: [
              const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: DC.teal)),
              const SizedBox(width: 10),
              Expanded(
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 300),
                  layoutBuilder: (current, previous) => Stack(
                    alignment: AlignmentDirectional.centerStart,
                    children: [...previous, ?current],
                  ),
                  transitionBuilder: (c, a) => FadeTransition(
                    opacity: a,
                    child: SlideTransition(position: Tween(begin: const Offset(0, .5), end: Offset.zero).animate(a), child: c),
                  ),
                  child: Text(tr('step.$current'), key: ValueKey(current),
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5)),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

class _StationLine extends StatelessWidget {
  const _StationLine({required this.at, required this.stations});
  final int at;
  final List<IconData> stations;

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, c) {
        final n = stations.length;
        final step = c.maxWidth / n;
        return SizedBox(
          height: 52,
          child: Stack(clipBehavior: Clip.none, children: [
            PositionedDirectional(
              start: step / 2,
              end: step / 2,
              top: 15,
              child: Container(height: 2, color: context.line),
            ),
            TweenAnimationBuilder<double>(
              tween: Tween(end: at.toDouble()),
              duration: const Duration(milliseconds: 700),
              curve: Curves.easeInOutCubic,
              builder: (context, v, _) => Stack(clipBehavior: Clip.none, children: [
                PositionedDirectional(
                  start: step / 2,
                  top: 15,
                  width: step * v,
                  child: Container(height: 2, decoration: const BoxDecoration(gradient: DC.brand)),
                ),
                for (var i = 0; i < n; i++)
                  PositionedDirectional(
                    start: step * i + step / 2 - 15,
                    top: 1,
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 300),
                      width: 30,
                      height: 30,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: i <= v.round() ? DC.brand : null,
                        color: i <= v.round() ? null : context.card2,
                        border: Border.all(color: i <= v.round() ? Colors.transparent : context.line),
                      ),
                      child: Icon(stations[i], size: 15, color: i <= v.round() ? DC.onBrand : context.faint),
                    ),
                  ),
                PositionedDirectional(
                  start: step * v + step / 2 - 10,
                  top: 33,
                  child: Transform.rotate(
                    angle: Directionality.of(context) == TextDirection.rtl ? -math.pi / 2 : math.pi / 2,
                    child: const Icon(Icons.flight_rounded, size: 20, color: DC.teal),
                  ),
                ),
              ]),
            ),
          ]),
        );
      });
}

/// The finished plan, printed out of a slot as a boarding pass (tap to open My trip).
class _PrintedPass extends StatelessWidget {
  const _PrintedPass({super.key, required this.state, required this.onOpen});
  final AppState state;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final c = state.trip!['trip_contract'] as Map<String, dynamic>;
    final stops = (c['stops'] as List?) ?? [];
    final cities = stops.isNotEmpty ? stops.map((s) => (s['ref'] as Map)['name']).toList() : [c['destination_name'] ?? c['destination']];
    final plan = state.plan!;
    final b = plan['budget'] as Map<String, dynamic>?;
    final score = (plan['score'] as Map?)?['total'];
    final out = plan['outbound_flight'] as Map<String, dynamic>? ??
        ((plan['legs'] as List?)?.isNotEmpty ?? false ? (plan['legs'] as List).first as Map<String, dynamic>? : null);
    final from = (out?['origin'] as String?) ?? '${c['origin_city'] ?? ''}';
    final to = (out?['destination'] as String?) ?? '${cities.first}';
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 1100),
      curve: Curves.easeOutCubic,
      builder: (context, v, child) => Align(
        alignment: AlignmentDirectional.centerStart,
        heightFactor: v,
        child: Opacity(opacity: v.clamp(0, 1), child: Transform.translate(offset: Offset(0, -30 * (1 - v)), child: child)),
      ),
      child: Padding(
        padding: const EdgeInsets.only(top: 6, bottom: 10),
        child: Tilt3D(
          child: Ticket(
            onTap: onOpen,
            main: Padding(
              padding: const EdgeInsets.fromLTRB(18, 16, 18, 10),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Text('✓ ${tr('tripReady')}'.toUpperCase(), style: mono(size: 10.5, color: DC.green, spacing: 1.2)),
                  const Spacer(),
                  if (score != null) Pill('${tr('tripScore')} $score', color: DC.teal),
                ]),
                const SizedBox(height: 12),
                Row(children: [
                  // Codes keep their width (a long city name is already shortened by _code); the arc takes the rest.
                  Text(_code(from), maxLines: 1, style: mono(size: 30, color: context.ink, weight: FontWeight.w800)),
                  const Expanded(child: Padding(padding: EdgeInsets.symmetric(horizontal: 10), child: FlyingRoute(height: 34))),
                  Text(_code(to), maxLines: 1, style: mono(size: 30, color: DC.teal, weight: FontWeight.w800)),
                ]),
                const SizedBox(height: 4),
                Text(routeText(cities), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 12.5)),
              ]),
            ),
            stub: Padding(
              padding: const EdgeInsets.fromLTRB(18, 2, 18, 14),
              child: Row(children: [
                Expanded(child: PassField(L('Dates', 'التواريخ'), '${fmtDate(c['start_date'])} – ${fmtDate(c['end_date'])}')),
                Expanded(child: PassField(tr('total'), money(b?['total'] as num?, b?['currency'] as String?), end: true, valueColor: DC.teal)),
                const SizedBox(width: 12),
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(gradient: DC.brand, borderRadius: BorderRadius.circular(14)),
                  child: Icon(isArabic ? Icons.arrow_back_rounded : Icons.arrow_forward_rounded, color: DC.onBrand),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }

  /// A 3-letter airport code stays as it is; a city name is shortened to fit the pass.
  static String _code(String s) => s.length <= 4 ? s.toUpperCase() : (s.length > 10 ? '${s.substring(0, 9)}.' : s);
}

/// The message box: a floating glass bar with the camera and the send plane.
class _Composer extends StatelessWidget {
  const _Composer({required this.controller, required this.busy, required this.onSend, required this.onCamera});
  final TextEditingController controller;
  final bool busy;
  final VoidCallback onSend;
  final VoidCallback onCamera;

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
          child: Container(
            padding: const EdgeInsetsDirectional.fromSTEB(6, 6, 6, 6),
            decoration: BoxDecoration(
              color: context.dark ? const Color(0xCC0F1626) : Colors.white.withValues(alpha: .85),
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: context.line),
            ),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              IconButton(
                tooltip: L('What\'s this place?', 'إيه المكان ده؟'),
                onPressed: onCamera,
                icon: Icon(Icons.photo_camera_outlined, color: context.muted),
              ),
              Expanded(
                child: TextField(
                  controller: controller,
                  minLines: 1,
                  maxLines: 5,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => onSend(),
                  decoration: InputDecoration(
                    hintText: tr('askPh'),
                    filled: false,
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                    contentPadding: const EdgeInsets.symmetric(vertical: 13),
                  ),
                ),
              ),
              const SizedBox(width: 4),
              Pressable(
                onTap: busy ? null : onSend,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 250),
                  width: 46,
                  height: 46,
                  decoration: BoxDecoration(
                    gradient: busy ? null : DC.brand,
                    color: busy ? context.card2 : null,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: busy
                      ? const Padding(padding: EdgeInsets.all(13), child: CircularProgressIndicator(strokeWidth: 2.2, color: DC.teal))
                      : Transform.rotate(
                          angle: isArabic ? -math.pi / 4 : math.pi / 4,
                          child: const Icon(Icons.flight_rounded, color: DC.onBrand),
                        ),
                ),
              ),
            ]),
          ),
        ),
      );
}
