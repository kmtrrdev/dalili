import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart' as fm;
import 'package:intl/intl.dart' hide TextDirection;
import 'package:latlong2/latlong.dart' show LatLng;
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';
import 'buddies_screen.dart';
import 'trip_helpers.dart';
import 'wallet_screen.dart';

const _miniH = 56.0; // the sticky mini-pass row

const _sections = ['days', 'stay', 'budget', 'weather', 'map'];

String _sectionLabel(String s) => switch (s) {
      'days' => tr('tabPlan'),
      'stay' => tr('tabStay'),
      'budget' => tr('tabBudget'),
      'weather' => tr('tabWeather'),
      _ => L('Map', 'الخريطة'),
    };

IconData _sectionIcon(String s) => switch (s) {
      'days' => Icons.view_day_rounded,
      'stay' => Icons.flight_takeoff_rounded,
      'budget' => Icons.pie_chart_rounded,
      'weather' => Icons.wb_sunny_rounded,
      _ => Icons.map_rounded,
    };

const _dayAccents = [DC.teal, DC.sky, DC.violet, DC.amber, DC.rose, DC.green];

double _textScale(BuildContext context) => (MediaQuery.textScalerOf(context).scale(16) / 16).clamp(1.0, 1.6);

/// My trip: the open trip as a boarding pass - the hero pass with its route, the four plans as tickets to swipe and
/// flip, then the days (a deck of cards), flights and hotels, the budget, the weather and the map. A tab (the shell
/// draws the sky); pushed on its own it brings its own sky and a back button.
class TripScreen extends StatefulWidget {
  const TripScreen({super.key, required this.state});
  final AppState state;

  @override
  State<TripScreen> createState() => _TripScreenState();
}

class _TripScreenState extends State<TripScreen> {
  final _scroll = ScrollController();
  final _segKey = GlobalKey();
  final _stuck = ValueNotifier(false);
  String _section = 'days';
  int _day = 0;
  int _seenVersion = -1;
  late Object _sig = _signature();

  AppState get st => widget.state;

  @override
  void initState() {
    super.initState();
    st.addListener(_onState);
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    st.removeListener(_onState);
    _scroll.dispose();
    _stuck.dispose();
    super.dispose();
  }

  // The state also changes on every step of a running chat turn: rebuild only when something shown here changed.
  Object _signature() => (identityHashCode(st.trip), st.planVersion, st.busy, st.trips.length, st.lang);

  void _onState() {
    final s = _signature();
    if (s != _sig && mounted) setState(() => _sig = s);
  }

  void _onScroll() {
    final box = _segKey.currentContext?.findRenderObject() as RenderBox?;
    if (box == null || !box.attached) return;
    _stuck.value = box.localToGlobal(Offset.zero).dy <= MediaQuery.paddingOf(context).top + _miniH;
  }

  bool get _pushed => ModalRoute.of(context)?.isFirst == false;

  void _goTab(int tab) {
    if (_pushed) Navigator.of(context).popUntil((r) => r.isFirst);
    st.goTab(tab);
  }

  void _select(String s) {
    if (s == _section) return;
    HapticFeedback.selectionClick();
    setState(() => _section = s);
    if (_stuck.value) {
      // Keep the section's top right under the sticky bar instead of jumping back to the hero.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final box = _segKey.currentContext?.findRenderObject() as RenderBox?;
        if (box == null || !_scroll.hasClients) return;
        final dy = box.localToGlobal(Offset.zero).dy - (MediaQuery.paddingOf(context).top + _miniH);
        _scroll.jumpTo((_scroll.offset + dy).clamp(0, _scroll.position.maxScrollExtent));
      });
    }
  }

  void _openDay(int i) => setState(() {
        _day = i;
        _section = 'days';
      });

  Future<void> _openBook() async {
    final id = st.tripId;
    if (id == null) return;
    try {
      final ok = await launchUrl(st.api.url('/api/trips/$id/book'),
          mode: LaunchMode.inAppWebView, webViewConfiguration: WebViewConfiguration(headers: st.api.identityHeaders));
      if (!ok && mounted) toast(context, tr('errNet'));
    } catch (_) {
      if (mounted) toast(context, tr('errNet'));
    }
  }

  void _whatIf() {
    if (st.busy) return toast(context, tr('busyWait'));
    showModalBottomSheet<void>(context: context, isScrollControlled: true, useSafeArea: true,
        builder: (_) => _WhatIfSheet(state: st));
  }

  void _rate() => showModalBottomSheet<void>(context: context, isScrollControlled: true, useSafeArea: true,
      builder: (_) => _RateSheet(state: st));

  void _buddies() => Navigator.of(context).push(passRoute(BuddiesScreen(state: st, tripId: st.tripId)));

  void _wallet() => Navigator.of(context).push(passRoute(WalletScreen(state: st)));

  @override
  Widget build(BuildContext context) {
    final trip = st.trip, plan = st.plan;
    if (st.planVersion != _seenVersion) {
      _seenVersion = st.planVersion;
      _day = 0;
    }
    Widget body = trip == null || plan == null
        ? _EmptyPass(state: st, pushed: _pushed, onPlan: () => _goTab(Tabs.chat), onWallet: _wallet)
        : _content(trip, plan);
    if (_pushed) body = SkyBackground(child: body);
    return Scaffold(backgroundColor: Colors.transparent, body: body);
  }

  Widget _content(Map<String, dynamic> trip, Map<String, dynamic> plan) {
    final days = asMaps(plan['days']);
    if (_day >= days.length) _day = 0;
    final top = MediaQuery.paddingOf(context).top;
    final bottom = _pushed ? MediaQuery.viewPaddingOf(context).bottom + 24 : context.dockSpace;
    final offers = asMaps(asMap(trip['metadata'])?['event_offers']);
    final segments = _Segments(selected: _section, onSelect: _select);
    return Stack(children: [
      RefreshIndicator(
        edgeOffset: top,
        onRefresh: () async {
          if (!st.busy && st.tripId != null) await st.openTrip(st.tripId!, quiet: true);
        },
        child: CustomScrollView(
          controller: _scroll,
          physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
          slivers: [
            SliverToBoxAdapter(
              child: _TopBar(
                top: top,
                pushed: _pushed,
                route: routeText(tripCities(trip)),
                onWallet: st.trips.isNotEmpty ? _wallet : null,
              ),
            ),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                child: KeyedSubtree(
                  key: ValueKey('hero${st.planVersion}'),
                  child: Reveal(child: RepaintBoundary(child: _HeroPass(trip: trip, plan: plan, tripId: st.tripId ?? ''))),
                ),
              ),
            ),
            SliverToBoxAdapter(
              child: _ActionsRow(actions: [
                (Icons.chat_bubble_rounded, L('Change it', 'غيّر حاجة'), DC.teal, () => _goTab(Tabs.chat)),
                (Icons.menu_book_rounded, L('Trip book', 'كتاب الرحلة'), DC.sky, _openBook),
                (Icons.tune_rounded, L('What if…', 'ماذا لو…'), DC.amber, _whatIf),
                (Icons.star_rounded, L('Rate plan', 'قيّم الخطة'), DC.rose, _rate),
                (Icons.groups_rounded, L('Buddies', 'رفقاء السفر'), DC.violet, _buddies),
                if (st.trips.isNotEmpty) (Icons.account_balance_wallet_rounded, tr('tripsTitle'), DC.green, _wallet),
              ]),
            ),
            SliverToBoxAdapter(child: _ModesCarousel(state: st)),
            if (offers.isNotEmpty)
              SliverToBoxAdapter(
                child: _EventOffers(offers: offers, plan: plan, onAdd: (o) {
                  if (st.busy) return toast(context, tr('busyWait'));
                  _goTab(Tabs.chat);
                  unawaited(st.send(L('Please add "${o['name']}" to my plan.', 'ضيف "${o['name']}" لخطتي من فضلك.')));
                }),
              ),
            SliverToBoxAdapter(
              child: Padding(
                key: _segKey,
                padding: const EdgeInsets.only(top: 18),
                child: segments,
              ),
            ),
            SliverToBoxAdapter(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 320),
                switchInCurve: Curves.easeOutCubic,
                switchOutCurve: Curves.easeInCubic,
                layoutBuilder: (cur, prev) => Stack(alignment: Alignment.topCenter, children: [...prev, ?cur]),
                transitionBuilder: (child, a) => FadeTransition(
                  opacity: a,
                  child: SlideTransition(position: Tween(begin: const Offset(0, .04), end: Offset.zero).animate(a), child: child),
                ),
                child: KeyedSubtree(key: ValueKey(_section), child: _sectionBody(trip, plan, days)),
              ),
            ),
            SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.fromLTRB(16, 22, 16, bottom),
                child: Column(children: [
                  _AskButton(onTap: () => _goTab(Tabs.chat)),
                  const SizedBox(height: 12),
                  Text(tr('priceNote'), textAlign: TextAlign.center, style: TextStyle(color: context.faint, fontSize: 11.5)),
                ]),
              ),
            ),
          ],
        ),
      ),
      PositionedDirectional(
        top: 0,
        start: 0,
        end: 0,
        child: ValueListenableBuilder<bool>(
          valueListenable: _stuck,
          builder: (context, stuck, child) => IgnorePointer(
            ignoring: !stuck,
            child: AnimatedSlide(
              offset: stuck ? Offset.zero : const Offset(0, -1),
              duration: const Duration(milliseconds: 280),
              curve: Curves.easeOutCubic,
              child: AnimatedOpacity(opacity: stuck ? 1 : 0, duration: const Duration(milliseconds: 200), child: child),
            ),
          ),
          child: _StickyBar(top: top, trip: trip, plan: plan, segments: segments),
        ),
      ),
    ]);
  }

  Widget _sectionBody(Map<String, dynamic> trip, Map<String, dynamic> plan, List<Map<String, dynamic>> days) {
    final cur = asMap(plan['budget'])?['currency'] as String?;
    return switch (_section) {
      'days' => _DaysSection(days: days, day: _day, cur: cur, onDay: (i) => setState(() => _day = i)),
      'stay' => _StaySection(plan: plan),
      'budget' => _BudgetSection(plan: plan, onWhatIf: _whatIf),
      'weather' => _WeatherSection(days: days, onDay: _openDay),
      _ => _MapSection(trip: trip, days: days, day: _day, onDay: (i) => setState(() => _day = i)),
    };
  }
}

// ---------------------------------------------------------------- top bar, sticky bar, segments
class _TopBar extends StatelessWidget {
  const _TopBar({required this.top, required this.pushed, required this.route, this.onWallet});
  final double top;
  final bool pushed;
  final String route;
  final VoidCallback? onWallet;

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsetsDirectional.fromSTEB(pushed ? 4 : 20, top + 8, 8, 4),
        child: Row(children: [
          if (pushed) const BackButton(),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(L('BOARDING PASS', 'بوردينج باس'),
                  style: mono(size: 10.5, spacing: 2, color: context.faint, weight: FontWeight.w800)),
              Text(route.isEmpty ? tr('tabTrip') : route, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: display(size: 24, color: context.ink)),
            ]),
          ),
          if (onWallet != null)
            IconButton(
              tooltip: tr('tripsTitle'),
              onPressed: onWallet,
              icon: const Icon(Icons.account_balance_wallet_rounded),
            ),
        ]),
      );
}

/// The mini pass that slides down once the sections reach the top: the route, the dates, the plan, and the
/// section tabs again.
class _StickyBar extends StatelessWidget {
  const _StickyBar({required this.top, required this.trip, required this.plan, required this.segments});
  final double top;
  final Map<String, dynamic> trip, plan;
  final Widget segments;

  @override
  Widget build(BuildContext context) {
    final c = asMap(trip['trip_contract']) ?? const {};
    final flights = planFlights(plan);
    final out = flights.isEmpty ? null : flights.first.$2;
    final cities = tripCities(trip);
    final from = passCode(out?['origin'] as String?, c['origin_city'] as String?);
    final to = passCode(out?['destination'] as String?, cities.isEmpty ? null : cities.first);
    final mode = '${trip['selected_mode'] ?? 'balanced'}';
    final accent = DC.mode[mode] ?? DC.teal;
    final score = asMap(plan['score'])?['total'];
    return Container(
      decoration: BoxDecoration(
        color: (context.dark ? DC.night : DC.day).withValues(alpha: .96),
        border: Border(bottom: BorderSide(color: context.line)),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .4 : .08), blurRadius: 18)],
      ),
      padding: EdgeInsets.only(top: top),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        SizedBox(
          height: _miniH,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(gradient: DC.brand, borderRadius: BorderRadius.circular(11)),
                child: Transform.rotate(
                    angle: isArabic ? -math.pi / 2 : math.pi / 2, child: const Icon(Icons.flight_rounded, size: 18, color: DC.onBrand)),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: AlignmentDirectional.centerStart,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text('$from  ${isArabic ? '←' : '→'}  $to', style: mono(size: 15, weight: FontWeight.w800, color: context.ink)),
                    Text('${fmtDate(c['start_date'] as String?)} – ${fmtDate(c['end_date'] as String?)}',
                        style: TextStyle(fontSize: 11.5, color: context.muted, fontWeight: FontWeight.w600)),
                  ]),
                ),
              ),
              Pill(tr('mode.$mode'), color: accent, icon: modeIcon[mode]),
              if (score != null) ...[
                const SizedBox(width: 8),
                Text('$score', style: mono(size: 16, color: accent)),
              ],
            ]),
          ),
        ),
        segments,
        const SizedBox(height: 6),
      ]),
    );
  }
}

class _Segments extends StatelessWidget {
  const _Segments({required this.selected, required this.onSelect});
  final String selected;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(children: [
          for (final s in _sections)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 8),
              child: Pressable(
                onTap: () => onSelect(s),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 240),
                  curve: Curves.easeOutCubic,
                  constraints: const BoxConstraints(minHeight: 44),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(
                    gradient: s == selected ? DC.brand : null,
                    color: s == selected ? null : context.card.withValues(alpha: .85),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: s == selected ? Colors.transparent : context.line),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(_sectionIcon(s), size: 17, color: s == selected ? DC.onBrand : context.muted),
                    const SizedBox(width: 6),
                    Text(_sectionLabel(s),
                        style: TextStyle(
                            fontWeight: FontWeight.w800, fontSize: 13, color: s == selected ? DC.onBrand : context.ink)),
                  ]),
                ),
              ),
            ),
        ]),
      );
}

/// Scales its content down instead of overflowing when a fixed-size face gets more text than it was drawn for
/// (larger system text, a long Arabic word).
class _Fit extends StatelessWidget {
  const _Fit({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, c) => FittedBox(
          fit: BoxFit.scaleDown,
          alignment: AlignmentDirectional.topStart,
          child: SizedBox(width: c.maxWidth, child: child),
        ),
      );
}

/// A pill for text that comes from the data (a weather condition, a neighbourhood): unlike [Pill] it shortens
/// with an ellipsis instead of overflowing a narrow pass.
class _Tag extends StatelessWidget {
  const _Tag(this.text, {required this.color, this.icon});
  final String text;
  final Color color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: context.dark ? .16 : .12),
          borderRadius: BorderRadius.circular(999),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 13, color: color), const SizedBox(width: 4)],
          Flexible(
            child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: color)),
          ),
        ]),
      );
}

/// The wide "ask Dalili" button at the end of the pass: the brand gradient, with a label that wraps.
class _AskButton extends StatelessWidget {
  const _AskButton({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 54),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          decoration: BoxDecoration(
            gradient: DC.brand,
            borderRadius: BorderRadius.circular(16),
            boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .28), blurRadius: 22, offset: const Offset(0, 8))],
          ),
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            const Icon(Icons.chat_bubble_rounded, color: DC.onBrand, size: 20),
            const SizedBox(width: 8),
            Flexible(
              child: Text(tr('askChange'), textAlign: TextAlign.center,
                  style: const TextStyle(color: DC.onBrand, fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ]),
        ),
      );
}

// ---------------------------------------------------------------- empty state
class _EmptyPass extends StatelessWidget {
  const _EmptyPass({required this.state, required this.pushed, required this.onPlan, required this.onWallet});
  final AppState state;
  final bool pushed;
  final VoidCallback onPlan, onWallet;

  @override
  Widget build(BuildContext context) {
    final faint = context.faint;
    return SafeArea(
      bottom: false,
      child: Column(children: [
        if (pushed) const Align(alignment: AlignmentDirectional.centerStart, child: BackButton()),
        Expanded(
          child: Center(
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(24, 24, 24, pushed ? 32 : context.dockSpace),
              child: Column(children: [
                Float(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 320),
                    child: Opacity(
                      opacity: .92,
                      child: Ticket(
                        main: Padding(
                          padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Row(children: [
                              Text('DALILI', style: mono(size: 12, spacing: 3, color: DC.teal, weight: FontWeight.w800)),
                              const Spacer(),
                              Text(L('NOT ISSUED', 'لسه ما اتطلعتش'), style: mono(size: 10, spacing: 1.5, color: faint)),
                            ]),
                            const SizedBox(height: 16),
                            Row(children: [
                              Text('???', style: mono(size: 32, weight: FontWeight.w800, color: faint)),
                              Expanded(
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(horizontal: 8),
                                  child: RouteArc(progress: .5, color: faint, height: 40),
                                ),
                              ),
                              Text('???', style: mono(size: 32, weight: FontWeight.w800, color: faint)),
                            ]),
                            const SizedBox(height: 14),
                            Row(children: [
                              Expanded(child: PassField(L('Depart', 'السفر'), '—')),
                              Expanded(child: PassField(L('Nights', 'ليالي'), '—')),
                              Expanded(child: PassField(tr('tripScore'), '—', end: true)),
                            ]),
                          ]),
                        ),
                        stub: Padding(
                          padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
                          child: Barcode('dalili-boarding-pass', height: 38, color: faint.withValues(alpha: .5)),
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 30),
                Text(L('No boarding pass yet', 'لسه مفيش بوردينج باس'),
                    textAlign: TextAlign.center, style: display(size: 24, color: context.ink)),
                const SizedBox(height: 8),
                Text(
                  L('Tell Dalili where you want to go - your trip lands here as a boarding pass.',
                      'قول لدليلي عايز تروح فين - رحلتك هتوصل هنا على شكل بوردينج باس.'),
                  textAlign: TextAlign.center,
                  style: TextStyle(color: context.muted, height: 1.4),
                ),
                if (state.busy) ...[
                  const SizedBox(height: 16),
                  Row(mainAxisSize: MainAxisSize.min, children: [
                    const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: DC.teal)),
                    const SizedBox(width: 10),
                    Flexible(child: Text(L('Dalili is planning your trip…', 'دليلي بيخطط رحلتك…'),
                        style: const TextStyle(fontWeight: FontWeight.w700, color: DC.teal))),
                  ]),
                ],
                const SizedBox(height: 24),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 300),
                  child: BrandButton(label: L('Plan with Dalili', 'خطط مع دليلي'), icon: Icons.chat_bubble_rounded, onTap: onPlan),
                ),
                if (state.trips.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 300),
                    child: SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        onPressed: onWallet,
                        icon: const Icon(Icons.account_balance_wallet_rounded, size: 19),
                        label: Text(L('Open my wallet', 'افتح محفظتي')),
                      ),
                    ),
                  ),
                ],
              ]),
            ),
          ),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------------- the hero pass
class _HeroPass extends StatelessWidget {
  const _HeroPass({required this.trip, required this.plan, required this.tripId});
  final Map<String, dynamic> trip, plan;
  final String tripId;

  @override
  Widget build(BuildContext context) {
    final c = asMap(trip['trip_contract']) ?? const {};
    final flights = planFlights(plan);
    final out = flights.isEmpty ? null : flights.first.$2;
    final cities = tripCities(trip);
    final fromCity = '${c['origin_city'] ?? ''}';
    final toCity = cities.isEmpty ? '' : cities.first;
    final fromCode = passCode(out?['origin'] as String?, fromCity);
    final toCode = passCode(out?['destination'] as String?, toCity);
    final mode = '${trip['selected_mode'] ?? 'balanced'}';
    final accent = DC.mode[mode] ?? DC.teal;
    final b = asMap(plan['budget']) ?? const {};
    final cur = b['currency'] as String?;
    final total = b['total'] as num?, limit = (b['limit'] as num?) ?? 0;
    final score = (asMap(plan['score'])?['total'] as num?)?.toInt();
    final pax = (c['travelers'] as num?)?.toInt() ?? 1;
    final nights = nightsBetween(c['start_date'] as String?, c['end_date'] as String?);
    final over = limit > 0 && (total ?? 0) > limit;

    Widget end(String code, String city, bool atEnd) => Column(
          crossAxisAlignment: atEnd ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            FittedBox(
              fit: BoxFit.scaleDown,
              child: SplitFlap(
                code,
                tile: isAirportCode(code),
                tileColor: context.dark ? const Color(0xFF0A0F1C) : const Color(0xFF14213D),
                delay: Duration(milliseconds: atEnd ? 380 : 120),
                style: isAirportCode(code)
                    ? mono(size: 30, weight: FontWeight.w800, color: Colors.white)
                    : display(size: 26, weight: FontWeight.w800, color: context.ink),
              ),
            ),
            const SizedBox(height: 4),
            if (isAirportCode(code) && city.isNotEmpty)
              Text(city, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12.5, color: context.muted, fontWeight: FontWeight.w600)),
          ],
        );

    return Tilt3D(
      maxAngle: .12,
      child: Ticket(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color.lerp(context.ticket, accent, context.dark ? .16 : .10)!, context.ticket],
        ),
        main: Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('DALILI', style: mono(size: 12, spacing: 3, color: accent, weight: FontWeight.w800)),
              const SizedBox(width: 8),
              Flexible(
                child: Text(L('BOARDING PASS', 'بوردينج باس'), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: mono(size: 10, spacing: 1.5, color: context.faint)),
              ),
              const Spacer(),
              Pill(tr('mode.$mode'), color: accent, icon: modeIcon[mode]),
            ]),
            const SizedBox(height: 6),
            FlyingRoute(color: accent, height: 46),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: end(fromCode, fromCity, false)),
              const SizedBox(width: 12),
              Expanded(child: end(toCode, toCity, true)),
            ]),
            if (cities.length > 1) ...[
              const SizedBox(height: 10),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (var i = 0; i < cities.length; i++)
                  _Tag('${i + 1}  ${cities[i]}', color: _dayAccents[i % _dayAccents.length]),
              ]),
            ],
            const SizedBox(height: 14),
            Row(children: [
              Expanded(child: PassField(L('Depart', 'السفر'), fmtDate(c['start_date'] as String?))),
              Expanded(child: PassField(L('Return', 'الرجوع'), fmtDate(c['end_date'] as String?))),
              Expanded(child: PassField(L('Nights', 'ليالي'), '$nights')),
              Expanded(child: PassField(L('Pax', 'مسافرين'), '$pax', end: true)),
            ]),
          ]),
        ),
        stub: Padding(
          padding: const EdgeInsets.fromLTRB(18, 10, 18, 16),
          child: Row(children: [
            if (score != null) ...[
              _ScoreRing(score: score, color: accent),
              const SizedBox(width: 12),
            ],
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                PassField(tr('total'), money(total, cur), valueColor: over ? DC.rose : null),
                const SizedBox(height: 2),
                Text(
                  limit > 0
                      ? (over ? tr('overBy', [money((total ?? 0) - limit, cur)]) : tr('remaining', [money(limit - (total ?? 0), cur)]))
                      : '',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: over ? DC.rose : DC.green),
                ),
              ]),
            ),
            const SizedBox(width: 10),
            SizedBox(
              width: 92,
              child: Column(children: [
                Barcode(tripId.isEmpty ? 'dalili' : tripId, height: 36),
                const SizedBox(height: 3),
                Text(tripId.length > 10 ? tripId.substring(tripId.length - 10).toUpperCase() : tripId.toUpperCase(),
                    style: mono(size: 8.5, color: context.faint, spacing: 1)),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _ScoreRing extends StatelessWidget {
  const _ScoreRing({required this.score, required this.color});
  final int score;
  final Color color;
  static const size = 54.0;

  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: score / 100),
        duration: const Duration(milliseconds: 1200),
        curve: Curves.easeOutCubic,
        builder: (context, v, _) => SizedBox(
          width: size,
          height: size,
          child: Stack(alignment: Alignment.center, children: [
            SizedBox.expand(
              child: CircularProgressIndicator(
                  value: v, strokeWidth: 5, backgroundColor: context.line, color: color, strokeCap: StrokeCap.round),
            ),
            Column(mainAxisSize: MainAxisSize.min, children: [
              Text('${(v * 100).round()}', style: mono(size: size * .3, color: context.ink, height: 1)),
              Text('SCORE', style: mono(size: size * .13, color: context.faint, weight: FontWeight.w800)),
            ]),
          ]),
        ),
      );
}

// ---------------------------------------------------------------- actions
class _ActionsRow extends StatelessWidget {
  const _ActionsRow({required this.actions});
  final List<(IconData, String, Color, VoidCallback)> actions;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(12, 18, 12, 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final (i, (icon, label, color, onTap)) in actions.indexed)
            Reveal(
              delay: Duration(milliseconds: 120 + i * 60),
              child: Pressable(
                onTap: onTap,
                child: SizedBox(
                  width: 78,
                  child: Column(children: [
                    Container(
                      width: 54,
                      height: 54,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: color.withValues(alpha: context.dark ? .16 : .14),
                        border: Border.all(color: color.withValues(alpha: .35)),
                      ),
                      child: Icon(icon, color: color, size: 24),
                    ),
                    const SizedBox(height: 6),
                    Text(label, textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: context.ink, height: 1.2)),
                  ]),
                ),
              ),
            ),
        ]),
      );
}

// ---------------------------------------------------------------- the four plans
/// The plans as tickets in a coverflow: swipe to choose one (it becomes the trip's plan), tap the one in front to
/// flip it over for its budget.
class _ModesCarousel extends StatefulWidget {
  const _ModesCarousel({required this.state});
  final AppState state;

  @override
  State<_ModesCarousel> createState() => _ModesCarouselState();
}

class _ModesCarouselState extends State<_ModesCarousel> {
  late final PageController _ctl = PageController(viewportFraction: .8, initialPage: _selIdx);
  final Set<String> _flipped = {};
  Timer? _debounce;
  String? _pending; // swiped to, not chosen yet
  String? _switching; // being chosen on the server
  bool _auto = false; // the carousel is following the trip, not the finger

  AppState get st => widget.state;
  List<String> get _modes {
    final plans = asMap(st.trip?['plans']) ?? const {};
    return [for (final m in planModes) if (plans.containsKey(m)) m];
  }

  int get _selIdx => math.max(0, _modes.indexOf('${st.trip?['selected_mode']}'));

  @override
  void dispose() {
    _debounce?.cancel();
    _ctl.dispose();
    super.dispose();
  }

  void _changed(int i) {
    if (_auto) return;
    HapticFeedback.selectionClick();
    _pending = _modes[i];
    _debounce?.cancel();
    // Wait for the swiping to settle: a quick swipe across three plans chooses only the last one.
    _debounce = Timer(const Duration(milliseconds: 420), () => _choose(_pending!));
  }

  Future<void> _choose(String m) async {
    if (m == st.trip?['selected_mode']) {
      setState(() => _pending = null);
      return;
    }
    setState(() => _switching = m);
    try {
      await st.selectMode(m);
    } catch (_) {
      if (mounted) toast(context, tr('errNet'));
    }
    if (!mounted) return;
    setState(() {
      _switching = null;
      _pending = null;
    });
  }

  void _follow() {
    // A new plan or a choice made elsewhere: bring its ticket to the front.
    if (_pending != null || _switching != null || !_ctl.hasClients || !_ctl.position.haveDimensions) return;
    final page = _ctl.page?.round();
    if (page == null || page == _selIdx) return;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || !_ctl.hasClients) return;
      _auto = true;
      await _ctl.animateToPage(_selIdx, duration: const Duration(milliseconds: 450), curve: Curves.easeOutCubic);
      _auto = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final modes = _modes;
    if (modes.isEmpty) return const SizedBox.shrink();
    _follow();
    final h = 268 * _textScale(context);
    final busy = st.busy;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(20, 18, 20, 0),
        child: Row(children: [
          Expanded(child: Text(L('Your plans', 'خططك'), style: display(size: 19, color: context.ink))),
          Text(L('swipe · tap to flip', 'اسحب · دوس للقلب'), style: TextStyle(fontSize: 11.5, color: context.faint)),
        ]),
      ),
      SizedBox(
        height: h,
        child: PageView.builder(
          controller: _ctl,
          itemCount: modes.length,
          physics: busy ? const NeverScrollableScrollPhysics() : const BouncingScrollPhysics(),
          onPageChanged: _changed,
          itemBuilder: (context, i) {
            final m = modes[i];
            final plan = asMap(asMap(st.trip?['plans'])?[m]) ?? const {};
            final chosen = st.trip?['selected_mode'] == m;
            return Coverflow(
              controller: _ctl,
              index: i,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(6, 12, 6, 14),
                child: Pressable(
                  scale: .98,
                  onTap: () {
                    final page = _ctl.hasClients ? (_ctl.page?.round() ?? _selIdx) : _selIdx;
                    if (page != i) {
                      if (!busy) _ctl.animateToPage(i, duration: const Duration(milliseconds: 380), curve: Curves.easeOutCubic);
                    } else {
                      setState(() => _flipped.contains(m) ? _flipped.remove(m) : _flipped.add(m));
                    }
                  },
                  child: Stack(children: [
                    FlipCard(
                      tapToFlip: false,
                      flipped: _flipped.contains(m),
                      front: _ModeFront(mode: m, plan: plan, chosen: chosen, height: h - 26),
                      back: _ModeBack(mode: m, plan: plan, height: h - 26),
                    ),
                    if (_switching == m)
                      Positioned.fill(
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: context.ticket.withValues(alpha: .6),
                            borderRadius: BorderRadius.circular(22),
                          ),
                          child: const Center(child: CircularProgressIndicator(color: DC.teal)),
                        ),
                      ),
                  ]),
                ),
              ),
            );
          },
        ),
      ),
      Center(
        child: AnimatedBuilder(
          animation: _ctl,
          builder: (context, _) {
            final page = _ctl.hasClients && _ctl.position.haveDimensions ? (_ctl.page ?? _selIdx.toDouble()) : _selIdx.toDouble();
            return Row(mainAxisSize: MainAxisSize.min, children: [
              for (var i = 0; i < modes.length; i++)
                Container(
                  margin: const EdgeInsets.symmetric(horizontal: 3),
                  width: 6 + 14 * (1 - (page - i).abs()).clamp(0.0, 1.0),
                  height: 6,
                  decoration: BoxDecoration(
                    color: (DC.mode[modes[i]] ?? DC.teal).withValues(alpha: .4 + .6 * (1 - (page - i).abs()).clamp(0.0, 1.0)),
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
            ]);
          },
        ),
      ),
      if (busy)
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 10, 20, 0),
          child: Row(children: [
            const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: DC.teal)),
            const SizedBox(width: 10),
            Expanded(
              child: Text(L('Dalili is working on your trip - you can switch plans when it\'s done.',
                  'دليلي شغال على رحلتك - تقدر تغيّر الخطة لما يخلص.'),
                  style: TextStyle(fontSize: 12, color: context.muted)),
            ),
          ]),
        ),
    ]);
  }
}

class _ModeFront extends StatelessWidget {
  const _ModeFront({required this.mode, required this.plan, required this.chosen, required this.height});
  final String mode;
  final Map<String, dynamic> plan;
  final bool chosen;
  final double height;

  @override
  Widget build(BuildContext context) {
    final accent = DC.mode[mode] ?? DC.teal;
    final b = asMap(plan['budget']) ?? const {};
    final cur = b['currency'] as String?;
    final total = (b['total'] as num?) ?? 0, limit = (b['limit'] as num?) ?? 0;
    final ratio = limit > 0 ? (total / limit).clamp(0.0, 1.0).toDouble() : 0.0;
    final over = limit > 0 && total > limit;
    final score = asMap(plan['score'])?['total'];
    final pitch = '${(isArabic && '${plan['pitch_ar'] ?? ''}'.isNotEmpty ? plan['pitch_ar'] : plan['pitch']) ?? ''}'.trim();
    final stubH = 62.0 * _textScale(context);
    return Ticket(
      elevation: chosen ? 12 : 6,
      borderColor: chosen ? accent.withValues(alpha: .6) : null,
      gradient: LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [Color.lerp(context.ticket, accent, context.dark ? .2 : .13)!, context.ticket],
      ),
      main: SizedBox(
        height: math.max(60, height - stubH - 22),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
          child: _Fit(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Row(children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(color: accent.withValues(alpha: .2), shape: BoxShape.circle),
                  child: Icon(modeIcon[mode], size: 18, color: accent),
                ),
                const SizedBox(width: 10),
                Expanded(child: Text(tr('mode.$mode'), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: display(size: 19, color: context.ink))),
                if (chosen) Pill(L('✓ Your plan', '✓ خطتك'), color: accent),
              ]),
              const SizedBox(height: 10),
              Text(money(total, cur), style: display(size: 26, color: over ? DC.rose : context.ink, height: 1.1)),
              Text(tr('ofBudget', [money(limit, cur)]), style: TextStyle(fontSize: 12, color: context.muted)),
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                    value: ratio, minHeight: 6, backgroundColor: context.line, color: over ? DC.rose : accent),
              ),
              if (pitch.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text(pitch, maxLines: 3, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 12.5, color: context.muted, height: 1.35)),
              ],
            ]),
          ),
        ),
      ),
      stub: SizedBox(
        height: stubH,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(children: [
            if (score != null) Flexible(child: PassField(tr('tripScore'), '$score', valueColor: accent)),
            const Spacer(),
            Icon(Icons.autorenew_rounded, size: 16, color: context.faint),
            const SizedBox(width: 4),
            Flexible(
              child: Text(tr('tabBudget'), maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 11.5, color: context.faint, fontWeight: FontWeight.w700)),
            ),
          ]),
        ),
      ),
    );
  }
}

class _ModeBack extends StatelessWidget {
  const _ModeBack({required this.mode, required this.plan, required this.height});
  final String mode;
  final Map<String, dynamic> plan;
  final double height;

  @override
  Widget build(BuildContext context) {
    final accent = DC.mode[mode] ?? DC.teal;
    final b = asMap(plan['budget']) ?? const {};
    final cur = b['currency'] as String?;
    final total = math.max(1, (b['total'] as num?) ?? 1);
    final remaining = (b['remaining'] as num?) ?? (((b['limit'] as num?) ?? 0) - ((b['total'] as num?) ?? 0));
    final stubH = 62.0 * _textScale(context);
    return Ticket(
      elevation: 6,
      color: Color.lerp(context.ticket, accent, context.dark ? .1 : .06),
      main: SizedBox(
        height: math.max(60, height - stubH - 22),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
          child: _Fit(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Row(children: [
                Text(tr('mode.$mode').toUpperCase(), style: mono(size: 11, spacing: 1.5, color: accent)),
                const Spacer(),
                Text(money(b['total'] as num?, cur), style: mono(size: 12, color: context.ink)),
              ]),
              const SizedBox(height: 8),
              for (final (label, key, color, icon) in budgetParts)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Column(children: [
                    Row(children: [
                      Icon(icon, size: 13, color: color),
                      const SizedBox(width: 6),
                      Expanded(child: Text(tr(label), style: TextStyle(fontSize: 11.5, color: context.muted, fontWeight: FontWeight.w600))),
                      Text(money(b[key] as num?, cur), style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800)),
                    ]),
                    const SizedBox(height: 3),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(3),
                      child: LinearProgressIndicator(
                        value: (((b[key] as num?) ?? 0) / total).clamp(0.0, 1.0).toDouble(),
                        minHeight: 3.5,
                        backgroundColor: context.line,
                        color: color,
                      ),
                    ),
                  ]),
                ),
            ]),
          ),
        ),
      ),
      stub: SizedBox(
        height: stubH,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(children: [
            Expanded(
              child: Text(
                remaining >= 0 ? tr('remaining', [money(remaining, cur)]) : tr('overBy', [money(-remaining, cur)]),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontWeight: FontWeight.w800, color: remaining >= 0 ? DC.green : DC.rose),
              ),
            ),
            Icon(Icons.autorenew_rounded, size: 16, color: context.faint),
          ]),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- big events during the trip
class _EventOffers extends StatelessWidget {
  const _EventOffers({required this.offers, required this.plan, required this.onAdd});
  final List<Map<String, dynamic>> offers;
  final Map<String, dynamic> plan;
  final ValueChanged<Map<String, dynamic>> onAdd;

  @override
  Widget build(BuildContext context) {
    final h = 200 * _textScale(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 22, 20, 2),
        child: Text(L('Big events on your dates', 'إيفنتات كبيرة في مواعيدك'), style: display(size: 19, color: context.ink)),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
        child: Text(L('Not in the plan unless you say so.', 'مش في الخطة غير لو طلبت.'),
            style: TextStyle(fontSize: 12, color: context.muted)),
      ),
      SizedBox(
        height: h,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          itemCount: offers.length,
          separatorBuilder: (_, _) => const SizedBox(width: 12),
          itemBuilder: (context, i) => SizedBox(width: 312, child: _EventTicket(offer: offers[i], plan: plan, onAdd: onAdd)),
        ),
      ),
    ]);
  }
}

class _EventTicket extends StatelessWidget {
  const _EventTicket({required this.offer, required this.plan, required this.onAdd});
  final Map<String, dynamic> offer;
  final Map<String, dynamic> plan;
  final ValueChanged<Map<String, dynamic>> onAdd;

  @override
  Widget build(BuildContext context) {
    final o = offer;
    final name = '${(isArabic && '${o['name_ar'] ?? ''}'.isNotEmpty ? o['name_ar'] : o['name']) ?? ''}';
    final why = '${(isArabic && '${o['why_ar'] ?? ''}'.isNotEmpty ? o['why_ar'] : o['why']) ?? ''}';
    final days = (o['trip_days'] as List?)?.map((e) => '$e').toList() ?? const <String>[];
    final first = DateTime.tryParse(days.isNotEmpty ? days.first : '${(o['event_dates'] as List?)?.first ?? ''}');
    final placeId = asMap(o['place'])?['id'] as String?;
    final inPlan = dayOfPlace(plan, placeId);
    final ticket = asMap(o['ticket']);
    final url = o['url'] as String?;
    final emoji = switch ('${o['category']}') { 'sports' => '🏟️', 'music' => '🎵', 'festival' => '🎉', _ => '🎟️' };
    const accent = DC.rose;
    return Ticket(
      axis: Axis.horizontal,
      radius: 20,
      notch: 11,
      gap: 18,
      elevation: 6,
      gradient: LinearGradient(colors: [Color.lerp(context.ticket, accent, context.dark ? .18 : .1)!, context.ticket]),
      main: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(14, 12, 6, 10),
        child: _Fit(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Text(emoji, style: const TextStyle(fontSize: 18)),
              const SizedBox(width: 6),
              Expanded(
                child: Text('${o['city'] ?? o['country_code'] ?? ''}'.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: mono(size: 10.5, spacing: 1.2, color: context.faint)),
              ),
            ]),
            const SizedBox(height: 4),
            Text(name, maxLines: 2, overflow: TextOverflow.ellipsis, style: display(size: 16, color: context.ink, height: 1.2)),
            if (why.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(why, maxLines: 2, overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 11.5, color: context.muted, height: 1.3)),
            ],
            const SizedBox(height: 8),
            if (inPlan != null)
              _Tag(L('✓ In your plan · day $inPlan', '✓ في خطتك · يوم $inPlan'), color: DC.green)
            else
              Wrap(spacing: 4, runSpacing: 2, crossAxisAlignment: WrapCrossAlignment.center, children: [
                if (placeId != null)
                  FilledButton(
                    style: FilledButton.styleFrom(
                        minimumSize: const Size(44, 40), padding: const EdgeInsets.symmetric(horizontal: 12),
                        textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800)),
                    onPressed: () => onAdd(o),
                    child: Text(L('Add to my plan', 'ضيفه لخطتي')),
                  ),
                if (url != null && url.isNotEmpty)
                  TextButton(
                    style: TextButton.styleFrom(minimumSize: const Size(44, 40)),
                    onPressed: () => openLink(url),
                    child: Text(L('Details', 'التفاصيل')),
                  ),
              ]),
          ]),
        ),
      ),
      stub: SizedBox(
        width: 74,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 4),
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('ADMIT', style: mono(size: 9, spacing: 2, color: accent)),
              Text('ONE', style: mono(size: 9, spacing: 2, color: accent)),
              const SizedBox(height: 8),
              if (first != null) ...[
                Text('${first.day}', style: mono(size: 26, color: context.ink, height: 1)),
                Text(DateFormat('MMM', isArabic ? 'ar' : 'en').format(first), style: TextStyle(fontSize: 12, color: context.muted)),
              ],
              const SizedBox(height: 8),
              Text(ticket == null ? L('free?', 'مجاني؟') : money(ticket['amount'] as num?, ticket['currency'] as String?),
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800)),
            ]),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- days
class _DaysSection extends StatelessWidget {
  const _DaysSection({required this.days, required this.day, required this.cur, required this.onDay});
  final List<Map<String, dynamic>> days;
  final int day;
  final String? cur;
  final ValueChanged<int> onDay;

  @override
  Widget build(BuildContext context) {
    if (days.isEmpty) return EmptyState(emoji: '🗓️', title: tr('noPlanYet'));
    final d = days[day];
    final items = asMaps(d['items']);
    final notes = (d['notes'] as List? ?? const []).map((e) => '$e').where((e) => e.trim().isNotEmpty).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _DayPicker(days: days, day: day, onDay: onDay),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
        child: _DayDeck(days: days, index: day, onChange: onDay),
      ),
      AnimatedSwitcher(
        duration: const Duration(milliseconds: 300),
        layoutBuilder: (cur, prev) => Stack(alignment: Alignment.topCenter, children: [...prev, ?cur]),
        child: Column(
          key: ValueKey(day),
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (var i = 0; i < items.length; i++)
              Reveal(
                delay: Duration(milliseconds: 40 * math.min(i, 8)),
                offset: 18,
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  if (asMap(items[i]['transport_from_previous']) case final leg? when i > 0 && ((leg['minutes'] as num?) ?? 0) > 0)
                    _LegRow(leg: leg),
                  Padding(
                    padding: EdgeInsets.fromLTRB(16, i == 0 ? 6 : 4, 16, 4),
                    child: _ItemPass(item: items[i]),
                  ),
                ]),
              ),
            if (notes.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 10, 20, 0),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final n in notes)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text('• $n', style: TextStyle(color: context.muted, fontSize: 12.5, height: 1.35)),
                    ),
                ]),
              ),
          ],
        ),
      ),
    ]);
  }
}

class _DayPicker extends StatefulWidget {
  const _DayPicker({required this.days, required this.day, required this.onDay});
  final List<Map<String, dynamic>> days;
  final int day;
  final ValueChanged<int> onDay;

  @override
  State<_DayPicker> createState() => _DayPickerState();
}

class _DayPickerState extends State<_DayPicker> {
  static const _chip = 72.0; // a chip and its gap
  late final _ctl = ScrollController(initialScrollOffset: math.max(0, widget.day * _chip - 120));

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(_DayPicker old) {
    super.didUpdateWidget(old);
    // A day chosen on the deck: bring its chip to the middle (only this strip scrolls, never the page).
    if (old.day != widget.day && _ctl.hasClients) {
      final p = _ctl.position;
      final target = (16 + widget.day * _chip - (p.viewportDimension - 64) / 2).clamp(0.0, p.maxScrollExtent);
      _ctl.animateTo(target, duration: const Duration(milliseconds: 300), curve: Curves.easeOutCubic);
    }
  }

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        controller: _ctl,
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
        child: Row(children: [
          for (var i = 0; i < widget.days.length; i++)
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 8),
              child: _DayChip(d: widget.days[i], n: i + 1, on: i == widget.day, onTap: () => widget.onDay(i)),
            ),
        ]),
      );
}

class _DayChip extends StatelessWidget {
  const _DayChip({required this.d, required this.n, required this.on, required this.onTap});
  final Map<String, dynamic> d;
  final int n;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final dt = DateTime.tryParse('${d['date'] ?? ''}');
    final w = asMap(d['weather']);
    final fg = on ? DC.onBrand : context.ink;
    return Pressable(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 240),
        curve: Curves.easeOutCubic,
        width: 64,
        padding: const EdgeInsets.symmetric(vertical: 8),
        transform: on ? (Matrix4.identity()..translateByDouble(0, -3, 0, 1)) : Matrix4.identity(),
        decoration: BoxDecoration(
          gradient: on ? DC.brand : null,
          color: on ? null : context.card.withValues(alpha: .9),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: on ? Colors.transparent : context.line),
          boxShadow: on ? [BoxShadow(color: DC.teal.withValues(alpha: .3), blurRadius: 14, offset: const Offset(0, 6))] : null,
        ),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(tr('day', [n]), maxLines: 1,
              style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: on ? DC.onBrand : context.muted)),
          Text(dt == null ? '–' : '${dt.day}', style: mono(size: 20, color: fg, height: 1.2)),
          Text(dt == null ? '' : DateFormat('EEE', isArabic ? 'ar' : 'en').format(dt), maxLines: 1,
              style: TextStyle(fontSize: 10.5, color: on ? DC.onBrand : context.faint, fontWeight: FontWeight.w600)),
          if (w != null) ...[
            const SizedBox(height: 2),
            Icon(weatherIcon(w['condition'] as String?), size: 14, color: on ? DC.onBrand : DC.amber),
          ],
        ]),
      ),
    );
  }
}

/// The day as the top card of a deck (the next days peek out under it): swipe it away for the next day, back for
/// the one before.
class _DayDeck extends StatefulWidget {
  const _DayDeck({required this.days, required this.index, required this.onChange});
  final List<Map<String, dynamic>> days;
  final int index;
  final ValueChanged<int> onChange;

  @override
  State<_DayDeck> createState() => _DayDeckState();
}

class _DayDeckState extends State<_DayDeck> with SingleTickerProviderStateMixin {
  double _dx = 0;
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 260));
  Animation<double>? _a;
  VoidCallback? _then;

  @override
  void initState() {
    super.initState();
    _c.addListener(() {
      if (_a != null) setState(() => _dx = _a!.value);
    });
    _c.addStatusListener((s) {
      if (s == AnimationStatus.completed) {
        final f = _then;
        _then = null;
        f?.call();
      }
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  void _animateTo(double x, {VoidCallback? then}) {
    _a = Tween(begin: _dx, end: x).animate(CurvedAnimation(parent: _c, curve: Curves.easeOutCubic));
    _then = then;
    _c.forward(from: 0);
  }

  void _end(DragEndDetails e, double w, bool rtl) {
    final v = e.primaryVelocity ?? 0;
    final dir = (_dx.abs() > 4 ? _dx : v).sign;
    // Swiping toward the reading start brings the next day (left in English, right in Arabic).
    final next = widget.index + (rtl ? dir : -dir).toInt();
    if ((_dx.abs() > w * .22 || v.abs() > 700) && dir != 0 && next >= 0 && next < widget.days.length) {
      HapticFeedback.selectionClick();
      _animateTo(dir * w * 1.15, then: () {
        widget.onChange(next);
        setState(() => _dx = 0);
      });
    } else {
      _animateTo(0);
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, c) {
        final w = c.maxWidth;
        final rtl = Directionality.of(context) == TextDirection.rtl;
        final rest = widget.days.length - widget.index - 1;
        final p = (_dx.abs() / w).clamp(0.0, 1.0);
        Widget ghost(int k) {
          final depth = (k - p).clamp(0.0, 2.0);
          return Positioned.fill(
            child: Transform(
              alignment: Alignment.bottomCenter,
              transform: Matrix4.identity()
                ..translateByDouble(0, 10 * depth, 0, 1)
                ..scaleByDouble(1 - .045 * depth, 1 - .045 * depth, 1, 1),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: Color.lerp(context.ticket, _dayAccents[(widget.index + k) % _dayAccents.length], .12),
                  borderRadius: BorderRadius.circular(22),
                  border: Border.all(color: context.ticketEdge),
                ),
              ),
            ),
          );
        }

        return GestureDetector(
          onHorizontalDragStart: (_) => _c.stop(),
          onHorizontalDragUpdate: (e) => setState(() => _dx += e.delta.dx),
          onHorizontalDragEnd: (e) => _end(e, w, rtl),
          child: Padding(
            padding: const EdgeInsets.only(bottom: 18),
            child: Stack(clipBehavior: Clip.none, children: [
              if (rest >= 2) ghost(2),
              if (rest >= 1) ghost(1),
              Transform(
                alignment: Alignment.bottomCenter,
                transform: Matrix4.identity()
                  ..translateByDouble(_dx, 0, 0, 1)
                  ..rotateZ(_dx / w * .1),
                child: _DayCard(d: widget.days[widget.index], count: widget.days.length,
                    accent: _dayAccents[widget.index % _dayAccents.length]),
              ),
            ]),
          ),
        );
      });
}

class _DayCard extends StatelessWidget {
  const _DayCard({required this.d, required this.count, required this.accent});
  final Map<String, dynamic> d;
  final int count;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final w = asMap(d['weather']);
    final km = (d['walking_km'] as num?) ?? 0;
    final cost = asMap(d['estimated_cost']);
    final city = '${d['city'] ?? ''}';
    return Ticket(
      elevation: 8,
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color.lerp(context.ticket, accent, context.dark ? .2 : .12)!, context.ticket],
      ),
      main: Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(tr('day', [d['day'] ?? '']).toUpperCase(), style: mono(size: 12, spacing: 1.5, color: accent)),
            Text('  / $count', style: mono(size: 12, color: context.faint, weight: FontWeight.w600)),
            const Spacer(),
            Icon(Icons.swipe_rounded, size: 18, color: context.faint),
          ]),
          const SizedBox(height: 6),
          Text('${d['title'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis,
              style: display(size: 20, color: context.ink, height: 1.2)),
          const SizedBox(height: 4),
          Text('${fmtDate(d['date'] as String?, year: true)}${city.isNotEmpty ? ' · $city' : ''}',
              style: TextStyle(fontSize: 12.5, color: context.muted, fontWeight: FontWeight.w600)),
        ]),
      ),
      stub: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
        child: Wrap(spacing: 8, runSpacing: 6, children: [
          if (w != null)
            _Tag('${w['condition'] ?? ''} · ${(w['temp_min_c'] as num?)?.round() ?? '–'}–${(w['temp_max_c'] as num?)?.round() ?? '–'}°',
                color: DC.sky, icon: weatherIcon(w['condition'] as String?)),
          if (km > 0) Pill('${km.toStringAsFixed(1)} km', color: DC.green, icon: Icons.directions_walk_rounded),
          if (((cost?['amount'] as num?) ?? 0) > 0)
            Pill('≈ ${money(cost!['amount'] as num?, cost['currency'] as String?)}', color: DC.amber, icon: Icons.payments_rounded),
          if (d['travel_day'] == true) Pill(L('Travel day', 'يوم سفر'), color: DC.violet, icon: Icons.flight_rounded),
        ]),
      ),
    );
  }
}

/// One stop of the day as a little ticket: what and how much on the main part, the time on the stub. Tap to read
/// the notes in full.
class _ItemPass extends StatefulWidget {
  const _ItemPass({required this.item});
  final Map<String, dynamic> item;

  @override
  State<_ItemPass> createState() => _ItemPassState();
}

class _ItemPassState extends State<_ItemPass> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final it = widget.item;
    final kind = '${it['kind'] ?? 'activity'}';
    final color = kindColor[kind] ?? DC.teal;
    final cost = asMap(it['cost']);
    final amount = (cost?['amount'] as num?) ?? 0;
    final type = cost?['price_type'] as String?;
    final notes = '${it['notes'] ?? ''}'.trim();
    final link = it['link'] as String?;
    final loc = asMap(it['location']);
    final long = notes.length > 90;
    return Ticket(
      axis: Axis.horizontal,
      radius: 18,
      notch: 9,
      gap: 14,
      elevation: 3,
      onTap: long ? () => setState(() => _open = !_open) : null,
      main: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(12, 12, 8, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(color: color.withValues(alpha: .16), shape: BoxShape.circle),
              child: Icon(kindIcon[kind] ?? Icons.place_rounded, size: 17, color: color),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text('${it['title'] ?? ''}', maxLines: _open ? 4 : 2, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5, height: 1.3)),
              ),
            ),
          ]),
          if (amount > 0 || it['optional'] == true) ...[
            const SizedBox(height: 8),
            Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              if (amount > 0)
                Text('${type == 'estimated' ? '≈ ' : ''}${money(amount, cost?['currency'] as String?)}',
                    style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13.5)),
              if (amount > 0)
                Pill(priceTypeLabel(type, menu: link != null), color: type == 'estimated' ? DC.violet : DC.green),
              if (it['optional'] == true) Pill(L('Optional', 'اختياري'), color: DC.amber),
            ]),
          ],
          if (notes.isNotEmpty) ...[
            const SizedBox(height: 6),
            AnimatedSize(
              duration: const Duration(milliseconds: 220),
              curve: Curves.easeOutCubic,
              alignment: AlignmentDirectional.topStart,
              child: Text(notes, maxLines: _open ? null : 2, overflow: _open ? null : TextOverflow.ellipsis,
                  style: TextStyle(color: context.muted, fontSize: 12.5, height: 1.35)),
            ),
          ],
          if (link != null || loc != null || long)
            Row(children: [
              if (long)
                Text(_open ? L('Less', 'أقل') : L('More', 'أكتر'),
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: DC.teal)),
              const Spacer(),
              if (link != null)
                TextButton(
                  style: TextButton.styleFrom(minimumSize: const Size(44, 44), padding: const EdgeInsets.symmetric(horizontal: 8)),
                  onPressed: () => openLink(link),
                  child: Text(kind == 'meal' ? tr('menu') : tr('website')),
                ),
              if (loc != null)
                IconButton(
                  tooltip: L('Map', 'الخريطة'),
                  onPressed: () => openLink('https://www.google.com/maps/search/?api=1&query=${loc['lat']},${loc['lon']}'),
                  icon: Icon(Icons.near_me_rounded, size: 19, color: context.muted),
                ),
            ]),
        ]),
      ),
      stub: SizedBox(
        width: 62,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Text('${it['start'] ?? ''}', style: mono(size: 14, color: context.ink)),
            Container(width: 1.4, height: 12, margin: const EdgeInsets.symmetric(vertical: 4), color: color.withValues(alpha: .6)),
            Text('${it['end'] ?? ''}', style: mono(size: 11.5, color: context.faint, weight: FontWeight.w600)),
          ]),
        ),
      ),
    );
  }
}

class _LegRow extends StatelessWidget {
  const _LegRow({required this.leg});
  final Map<String, dynamic> leg;

  @override
  Widget build(BuildContext context) {
    final mins = (leg['minutes'] as num?)?.toInt() ?? 0;
    final km = (leg['distance_km'] as num?) ?? 0;
    final cost = asMap(leg['cost']);
    final amount = (cost?['amount'] as num?) ?? 0;
    final parts = [
      L('$mins min', '$mins دقيقة'),
      if (km > 0) '${km.toStringAsFixed(km < 10 ? 1 : 0)} km',
      if (amount > 0) money(amount, cost?['currency'] as String?),
    ];
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(40, 2, 16, 2),
      child: Row(children: [
        SizedBox(width: 2, height: 26, child: CustomPaint(painter: _DotsPainter(context.faint))),
        const SizedBox(width: 12),
        Icon(legIcon[leg['mode']] ?? Icons.route_rounded, size: 16, color: context.muted),
        const SizedBox(width: 6),
        Expanded(
          child: Text(parts.join(' · '), maxLines: 1, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: context.muted, fontWeight: FontWeight.w600)),
        ),
      ]),
    );
  }
}

class _DotsPainter extends CustomPainter {
  _DotsPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()..color = color;
    for (var y = 2.0; y < size.height; y += 6) {
      canvas.drawCircle(Offset(size.width / 2, y), 1.2, p);
    }
  }

  @override
  bool shouldRepaint(_DotsPainter old) => old.color != color;
}

// ---------------------------------------------------------------- flights + hotels
class _StaySection extends StatelessWidget {
  const _StaySection({required this.plan});
  final Map<String, dynamic> plan;

  @override
  Widget build(BuildContext context) {
    final flights = planFlights(plan);
    final hotels = planHotels(plan);
    if (flights.isEmpty && hotels.isEmpty) return EmptyState(emoji: '🧳', title: tr('noPlanYet'));
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final (i, (label, f)) in flights.indexed)
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Reveal(delay: Duration(milliseconds: 60 * i), child: _FlightPass(label: label, f: f)),
          ),
        for (final (i, (city, h)) in hotels.indexed)
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Reveal(delay: Duration(milliseconds: 60 * (i + flights.length)), child: _HotelPass(city: city, h: h)),
          ),
      ]),
    );
  }
}

class _FlightPass extends StatelessWidget {
  const _FlightPass({required this.label, required this.f});
  final String label;
  final Map<String, dynamic> f;

  @override
  Widget build(BuildContext context) {
    final mins = (f['duration_minutes'] as num?)?.toInt() ?? 0;
    final stops = (f['stops'] as num?)?.toInt() ?? 0;
    final price = asMap(f['price_per_person']);
    final kind = f['mode'] as String?;
    final flying = kind == null || kind == 'flight';
    final from = passCode(f['origin'] as String?, null), to = passCode(f['destination'] as String?, null);
    final rtl = Directionality.of(context) == TextDirection.rtl;

    Widget end(String code, String? iso, bool atEnd) => Column(
          crossAxisAlignment: atEnd ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            FittedBox(fit: BoxFit.scaleDown, child: Text(code, style: mono(size: 28, color: context.ink, height: 1.1))),
            Text(clockOf(iso), style: display(size: 17, color: context.ink)),
            Text(fmtDate(iso), style: TextStyle(fontSize: 11.5, color: context.faint, fontWeight: FontWeight.w600)),
          ],
        );

    return Ticket(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color.lerp(context.ticket, DC.sky, context.dark ? .16 : .1)!, context.ticket],
      ),
      main: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Pill(label, color: DC.sky, icon: journeyIcon(kind)),
            const SizedBox(width: 8),
            Expanded(
              child: Text('${f['airline'] ?? ''}', maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700)),
            ),
            Text('${f['flight_number'] ?? ''}', style: mono(size: 12, color: context.faint)),
          ]),
          const SizedBox(height: 14),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Flexible(child: end(from, f['depart_at'] as String?, false)),
            Expanded(
              flex: 2,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(10, 6, 10, 0),
                child: Column(children: [
                  Text(durationLabel(mins), style: TextStyle(fontSize: 12, color: context.muted, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 4),
                  Row(children: [
                    Expanded(child: SizedBox(height: 2, child: CustomPaint(painter: _HDotsPainter(DC.sky.withValues(alpha: .7))))),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: flying
                          ? Transform.rotate(angle: rtl ? -math.pi / 2 : math.pi / 2,
                              child: const Icon(Icons.flight_rounded, size: 20, color: DC.sky))
                          : Icon(journeyIcon(kind), size: 20, color: DC.sky),
                    ),
                    Expanded(child: SizedBox(height: 2, child: CustomPaint(painter: _HDotsPainter(DC.sky.withValues(alpha: .7))))),
                  ]),
                  const SizedBox(height: 4),
                  Text(
                    stops == 0 ? tr('direct') : '${tr('stopsN', [stops])}${f['via'] != null ? ' · ${f['via']}' : ''}',
                    textAlign: TextAlign.center,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: stops == 0 ? DC.green : context.muted),
                  ),
                ]),
              ),
            ),
            Flexible(child: end(to, f['arrive_at'] as String?, true)),
          ]),
        ]),
      ),
      stub: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
        child: Column(children: [
          Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                PassField(L('Fare', 'السعر'), money(price?['amount'] as num?, price?['currency'] as String?)),
                Text(tr('perPerson'), style: TextStyle(fontSize: 11, color: context.muted)),
              ]),
            ),
            const SizedBox(width: 10),
            SizedBox(width: 104, child: Barcode('${f['id'] ?? f['flight_number'] ?? label}', height: 34)),
          ]),
          if (f['booking_url'] != null) ...[
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () => openLink(f['booking_url'] as String),
                icon: const Icon(Icons.open_in_new_rounded, size: 18),
                label: Text(tr('book')),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}

class _HDotsPainter extends CustomPainter {
  _HDotsPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()..color = color;
    for (var x = 1.0; x < size.width; x += 6) {
      canvas.drawCircle(Offset(x, size.height / 2), 1.2, p);
    }
  }

  @override
  bool shouldRepaint(_HDotsPainter old) => old.color != color;
}

class _HotelPass extends StatelessWidget {
  const _HotelPass({required this.city, required this.h});
  final String? city;
  final Map<String, dynamic> h;

  @override
  Widget build(BuildContext context) {
    final images = (h['images'] as List? ?? const []).map((e) => '$e').where((e) => e.startsWith('http')).toList();
    final night = asMap(h['price_per_night']);
    final total = asMap(h['total_price']);
    final stars = (h['stars'] as num?)?.toInt() ?? 0;
    final loc = asMap(h['location']);
    final link = h['link'] as String?;
    final insights = asMap(h['review_insights']) ?? const {};
    final summaryAr = '${insights['summary_ar'] ?? ''}';
    final summary = isArabic && summaryAr.isNotEmpty ? summaryAr : '${insights['summary'] ?? ''}';
    final google = 'https://www.google.com/travel/search?q=${Uri.encodeComponent('${h['name']}${city != null ? ' $city' : ''}')}';
    // The photos sit on their own card clipped above the pass: a PageView inside a Ticket would composite, which
    // the Ticket's painting doesn't support yet (see the report).
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: ClipRRect(
          borderRadius: const BorderRadius.vertical(top: Radius.circular(22)),
          child: SizedBox(height: 176, child: _PhotoPager(images: images)),
        ),
      ),
      Ticket(
      main: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (city != null) Text(city!.toUpperCase(), style: mono(size: 10.5, spacing: 1.5, color: DC.violet)),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: Text('${h['name'] ?? ''}', style: display(size: 18, color: context.ink, height: 1.2))),
              if (stars > 0)
                Padding(
                  padding: const EdgeInsetsDirectional.only(start: 8, top: 4),
                  child: Text('★' * stars, style: const TextStyle(color: DC.amber, fontSize: 13)),
                ),
            ]),
            const SizedBox(height: 8),
            Wrap(spacing: 6, runSpacing: 6, children: [
              if (h['rating'] != null) Pill('${h['rating']} · ${h['reviews_count'] ?? 0}', color: DC.amber, icon: Icons.star_rounded),
              if ('${h['neighborhood'] ?? ''}'.isNotEmpty) _Tag('${h['neighborhood']}', color: DC.violet, icon: Icons.location_on_rounded),
              if (h['breakfast_included'] == true) Pill(tr('breakfast'), color: DC.green, icon: Icons.free_breakfast_rounded),
              if (h['free_cancellation'] == true) Pill(L('Free cancellation', 'إلغاء مجاني'), color: DC.teal, icon: Icons.event_available_rounded),
            ]),
            if (summary.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('“$summary”', maxLines: 3, overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 12.5, color: context.muted, height: 1.35, fontStyle: FontStyle.italic)),
            ],
          ]),
        ),
      ]),
      stub: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Wrap(spacing: 12, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.end, children: [
            Row(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(money(night?['amount'] as num?, night?['currency'] as String?), style: display(size: 22, color: context.ink)),
              Text(' ${tr('perNight')}', style: TextStyle(color: context.muted, fontSize: 12.5)),
            ]),
            if (total != null)
              Text('${tr('stayTotal')}: ${money(total['amount'] as num?, total['currency'] as String?)}',
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12.5)),
          ]),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: () => openLink(google),
                icon: const Icon(Icons.hotel_rounded, size: 18),
                label: Text(tr('book'), maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ),
            if (link != null) ...[
              const SizedBox(width: 8),
              OutlinedButton(onPressed: () => openLink(link), child: Text(tr('website'))),
            ],
            if (loc != null) ...[
              const SizedBox(width: 8),
              IconButton.outlined(
                tooltip: L('Map', 'الخريطة'),
                onPressed: () => openLink('https://www.google.com/maps/search/?api=1&query=${loc['lat']},${loc['lon']}'),
                icon: const Icon(Icons.map_outlined),
              ),
            ],
          ]),
        ]),
      ),
      ),
    ]);
  }
}

class _PhotoPager extends StatefulWidget {
  const _PhotoPager({required this.images});
  final List<String> images;

  @override
  State<_PhotoPager> createState() => _PhotoPagerState();
}

class _PhotoPagerState extends State<_PhotoPager> {
  final _ctl = PageController();
  int _i = 0;

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final imgs = widget.images.take(8).toList();
    if (imgs.isEmpty) return const PlacePhoto(emoji: '🏨', tint: DC.violet);
    return Stack(children: [
      PageView.builder(
        controller: _ctl,
        itemCount: imgs.length,
        onPageChanged: (i) => setState(() => _i = i),
        itemBuilder: (_, i) => PlacePhoto(url: imgs[i], emoji: '🏨', tint: DC.violet),
      ),
      if (imgs.length > 1)
        PositionedDirectional(
          bottom: 10,
          start: 0,
          end: 0,
          child: IgnorePointer(
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              for (var i = 0; i < imgs.length; i++)
                AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  margin: const EdgeInsets.symmetric(horizontal: 2.5),
                  width: i == _i ? 16 : 6,
                  height: 6,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: i == _i ? .95 : .55),
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
            ]),
          ),
        ),
    ]);
  }
}

// ---------------------------------------------------------------- budget
class _BudgetSection extends StatelessWidget {
  const _BudgetSection({required this.plan, required this.onWhatIf});
  final Map<String, dynamic> plan;
  final VoidCallback onWhatIf;

  @override
  Widget build(BuildContext context) {
    final b = asMap(plan['budget']) ?? const {};
    final cur = b['currency'] as String?;
    final total = (b['total'] as num?) ?? 0, limit = (b['limit'] as num?) ?? 0;
    final over = limit > 0 && total > limit;
    final parts = [for (final p in budgetParts) (p, ((b[p.$2] as num?) ?? 0).toDouble())];
    final sum = math.max(1.0, parts.fold<double>(0, (s, e) => s + e.$2));
    final daily = (asMap(b['daily_spending']) ?? const {}).entries.toList()..sort((a, c) => a.key.compareTo(c.key));
    final maxDay = daily.fold<double>(1, (m, e) => math.max(m, ((e.value as num?) ?? 0).toDouble()));
    final trust = asMap(b['by_trust']) ?? const {};
    final trustParts = [
      ('verified', L('Published', 'منشور'), DC.green),
      ('calculated', L('Calculated', 'محسوب'), DC.teal),
      ('estimated', L('Estimated', 'تقديري'), DC.amber),
      ('unknown', L('Typical', 'متوسط'), DC.rose),
    ].map((e) => (e, ((trust[e.$1] as num?) ?? 0).toDouble())).where((e) => e.$2 > 0).toList();
    final trustSum = trustParts.fold<double>(0, (s, e) => s + e.$2);
    final notes = (b['notes'] as List? ?? const []).map((e) => '$e').toList();

    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 1100),
      curve: Curves.easeOutCubic,
      builder: (context, t, _) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _Panel(
            child: Column(children: [
              SizedBox(
                width: 196,
                height: 196,
                child: CustomPaint(
                  painter: _RingPainter([for (final (p, v) in parts) (v / sum, p.$3)], t, context.line),
                  child: Center(
                    child: Padding(
                      padding: const EdgeInsets.all(30),
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Column(mainAxisSize: MainAxisSize.min, children: [
                          Text(money(total * t, cur), style: display(size: 24, color: over ? DC.rose : context.ink)),
                          Text(tr('ofBudget', [money(limit, cur)]), style: TextStyle(fontSize: 12, color: context.muted)),
                        ]),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Pill(
                over ? tr('overBy', [money(total - limit, cur)]) : tr('remaining', [money(limit - total, cur)]),
                color: over ? DC.rose : DC.green,
              ),
              const SizedBox(height: 14),
              for (final (p, v) in parts)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(children: [
                    Container(
                      width: 34,
                      height: 34,
                      decoration: BoxDecoration(color: p.$3.withValues(alpha: .15), borderRadius: BorderRadius.circular(10)),
                      child: Icon(p.$4, size: 18, color: p.$3),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Row(children: [
                          Expanded(child: Text(tr(p.$1), style: const TextStyle(fontWeight: FontWeight.w700))),
                          Text(money(v, cur), style: const TextStyle(fontWeight: FontWeight.w800)),
                        ]),
                        const SizedBox(height: 6),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: LinearProgressIndicator(
                              value: (v / sum * t).clamp(0.0, 1.0), minHeight: 7, backgroundColor: context.line, color: p.$3),
                        ),
                      ]),
                    ),
                  ]),
                ),
            ]),
          ),
          if (trustParts.isNotEmpty) ...[
            const SizedBox(height: 12),
            _Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(L('How sure the prices are', 'الأسعار متأكدة قد إيه'), style: display(size: 16, color: context.ink)),
                const SizedBox(height: 10),
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: SizedBox(
                    height: 10,
                    child: Row(children: [
                      for (final (e, v) in trustParts)
                        Expanded(flex: math.max(1, (v / trustSum * 1000).round()), child: ColoredBox(color: e.$3)),
                    ]),
                  ),
                ),
                const SizedBox(height: 10),
                Wrap(spacing: 12, runSpacing: 6, children: [
                  for (final (e, v) in trustParts)
                    Row(mainAxisSize: MainAxisSize.min, children: [
                      Container(width: 9, height: 9, decoration: BoxDecoration(color: e.$3, shape: BoxShape.circle)),
                      const SizedBox(width: 5),
                      Text('${e.$2} ${(v / trustSum * 100).round()}%',
                          style: TextStyle(fontSize: 12, color: context.muted, fontWeight: FontWeight.w600)),
                    ]),
                ]),
              ]),
            ),
          ],
          if (daily.isNotEmpty) ...[
            const SizedBox(height: 12),
            _Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(L('Spending per day', 'المصروف اليومي'), style: display(size: 16, color: context.ink)),
                const SizedBox(height: 12),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                    for (final (i, e) in daily.indexed)
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: SizedBox(
                          width: 40,
                          child: Column(mainAxisSize: MainAxisSize.min, children: [
                            FittedBox(
                              fit: BoxFit.scaleDown,
                              child: Text(money(e.value as num?, cur), style: TextStyle(fontSize: 9.5, color: context.muted)),
                            ),
                            const SizedBox(height: 4),
                            Container(
                              height: 4 + 96 * (((e.value as num?) ?? 0) / maxDay) *
                                  Curves.easeOutBack.transform((t * 1.4 - i * .06).clamp(0.0, 1.0)).clamp(0.0, 1.2),
                              decoration: BoxDecoration(gradient: DC.brand, borderRadius: BorderRadius.circular(6)),
                            ),
                            const SizedBox(height: 4),
                            Text(e.key.length >= 10 ? e.key.substring(8, 10) : e.key,
                                style: mono(size: 11, color: context.ink)),
                          ]),
                        ),
                      ),
                  ]),
                ),
              ]),
            ),
          ],
          const SizedBox(height: 12),
          Pressable(
            onTap: onWhatIf,
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                gradient: LinearGradient(colors: [DC.amber.withValues(alpha: .22), DC.coral.withValues(alpha: .12)]),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: DC.amber.withValues(alpha: .35)),
              ),
              child: Row(children: [
                const Icon(Icons.tune_rounded, color: DC.amber, size: 28),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(L('What if… I change the budget?', 'ماذا لو… غيّرت الميزانية؟'), style: display(size: 16, color: context.ink)),
                    const SizedBox(height: 2),
                    Text(L('Compare on a copy - nothing changes until you apply.', 'قارن على نسخة - مفيش حاجة بتتغير غير لما توافق.'),
                        style: TextStyle(fontSize: 12, color: context.muted)),
                  ]),
                ),
                Icon(isArabic ? Icons.chevron_left_rounded : Icons.chevron_right_rounded, color: context.faint),
              ]),
            ),
          ),
          if (notes.isNotEmpty) ...[
            const SizedBox(height: 12),
            for (final n in notes)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('• $n', style: TextStyle(color: context.muted, fontSize: 12.5, height: 1.35)),
              ),
          ],
        ]),
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: context.ticket.withValues(alpha: .94),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: context.ticketEdge),
          boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .3 : .06), blurRadius: 18, offset: const Offset(0, 8))],
        ),
        child: child,
      );
}

/// The budget as a ring: one arc per part, drawn in as [t] goes from 0 to 1.
class _RingPainter extends CustomPainter {
  _RingPainter(this.parts, this.t, this.track);
  final List<(double, Color)> parts;
  final double t;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 18.0;
    final rect = Rect.fromCircle(center: size.center(Offset.zero), radius: size.shortestSide / 2 - stroke / 2);
    canvas.drawArc(rect, 0, math.pi * 2, false, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = track);
    var a = -math.pi / 2;
    final full = math.pi * 2 * t;
    for (final (frac, color) in parts) {
      if (frac <= 0) continue;
      final sweep = math.min(frac * math.pi * 2, math.max(0.0, -math.pi / 2 + full - a));
      if (sweep <= 0) break;
      canvas.drawArc(rect, a + .02, math.max(0.0, sweep - .04), false, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.butt
        ..color = color);
      a += frac * math.pi * 2;
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.t != t || old.track != track || old.parts.length != parts.length;
}

// ---------------------------------------------------------------- weather
class _WeatherSection extends StatelessWidget {
  const _WeatherSection({required this.days, required this.onDay});
  final List<Map<String, dynamic>> days;
  final ValueChanged<int> onDay;

  @override
  Widget build(BuildContext context) {
    final rows = [for (final (i, d) in days.indexed) if (asMap(d['weather']) != null) (i, asMap(d['weather'])!)];
    if (rows.isEmpty) {
      return EmptyState(emoji: '⛅', title: L('No forecast yet', 'لسه مفيش توقعات'),
          subtitle: L('The forecast appears about two weeks before the trip.', 'التوقعات بتظهر قبل الرحلة بحوالي أسبوعين.'));
    }
    double t(Map<String, dynamic> w, String k) => ((w[k] as num?) ?? 0).toDouble();
    final lo = rows.map((r) => t(r.$2, 'temp_min_c')).reduce(math.min);
    final hi = rows.map((r) => t(r.$2, 'temp_max_c')).reduce(math.max);
    final span = math.max(1.0, hi - lo);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
      child: _Panel(
        child: Column(children: [
          for (final (n, (i, w)) in rows.indexed) ...[
            if (n > 0) Divider(height: 1, color: context.line),
            InkWell(
              borderRadius: BorderRadius.circular(12),
              onTap: () => onDay(i),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 56),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(children: [
                    SizedBox(
                      width: 62,
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(tr('day', [i + 1]), style: TextStyle(fontSize: 11, color: context.faint, fontWeight: FontWeight.w700)),
                        Text(fmtDate(w['date'] as String? ?? days[i]['date'] as String?),
                            maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
                      ]),
                    ),
                    Icon(weatherIcon(w['condition'] as String?), size: 26,
                        color: t(w, 'precipitation_probability') > 40 ? DC.sky : DC.amber),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${w['condition'] ?? ''}', maxLines: 1, overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
                        const SizedBox(height: 4),
                        // Where today's range sits within the whole trip's.
                        LayoutBuilder(builder: (context, c) {
                          final a = (t(w, 'temp_min_c') - lo) / span, b = (t(w, 'temp_max_c') - lo) / span;
                          return Container(
                            height: 6,
                            decoration: BoxDecoration(color: context.line, borderRadius: BorderRadius.circular(3)),
                            child: Stack(children: [
                              PositionedDirectional(
                                start: c.maxWidth * a,
                                width: math.max(6, c.maxWidth * (b - a)),
                                top: 0,
                                bottom: 0,
                                child: DecoratedBox(
                                  decoration: BoxDecoration(
                                    gradient: const LinearGradient(colors: [DC.sky, DC.amber]),
                                    borderRadius: BorderRadius.circular(3),
                                  ),
                                ),
                              ),
                            ]),
                          );
                        }),
                        const SizedBox(height: 3),
                        Text(tr('rain', [t(w, 'precipitation_probability').round()]),
                            style: TextStyle(fontSize: 11, color: context.muted)),
                      ]),
                    ),
                    const SizedBox(width: 10),
                    Text('${t(w, 'temp_max_c').round()}°', style: mono(size: 16, color: context.ink)),
                    Text(' / ${t(w, 'temp_min_c').round()}°', style: mono(size: 12, color: context.faint, weight: FontWeight.w600)),
                  ]),
                ),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- map (built only when its section is open)
class _MapSection extends StatelessWidget {
  const _MapSection({required this.trip, required this.days, required this.day, required this.onDay});
  final Map<String, dynamic> trip;
  final List<Map<String, dynamic>> days;
  final int day;
  final ValueChanged<int> onDay;

  @override
  Widget build(BuildContext context) {
    final items = days.isEmpty ? const <Map<String, dynamic>>[] : asMaps(days[day]['items']);
    final stops = [
      for (final it in items)
        if (asMap(it['location']) case final l? when l['lat'] is num && l['lon'] is num)
          (LatLng((l['lat'] as num).toDouble(), (l['lon'] as num).toDouble()), it),
    ];
    final ref = asMap(asMap(trip['trip_contract'])?['destination_ref']);
    final fallback = ref != null && ref['lat'] is num ? LatLng((ref['lat'] as num).toDouble(), (ref['lon'] as num).toDouble()) : null;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (days.isNotEmpty) _DayPicker(days: days, day: day, onDay: onDay),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
        child: stops.isEmpty && fallback == null
            ? EmptyState(emoji: '🗺️', title: L('No places to show on this day', 'مفيش أماكن تتعرض اليوم ده'))
            : _DayMap(key: ValueKey('map$day'), stops: stops, fallback: fallback),
      ),
    ]);
  }
}

class _DayMap extends StatefulWidget {
  const _DayMap({super.key, required this.stops, this.fallback, this.full = false});
  final List<(LatLng, Map<String, dynamic>)> stops;
  final LatLng? fallback;
  final bool full;

  @override
  State<_DayMap> createState() => _DayMapState();
}

class _DayMapState extends State<_DayMap> {
  final _map = fm.MapController();
  int? _focus;

  @override
  void dispose() {
    _map.dispose();
    super.dispose();
  }

  void _go(int i) {
    setState(() => _focus = i);
    _map.move(widget.stops[i].$1, 16);
  }

  Widget _mapView(BuildContext context) {
    final pts = [for (final s in widget.stops) s.$1];
    return fm.FlutterMap(
      mapController: _map,
      options: fm.MapOptions(
        initialCenter: pts.isNotEmpty ? pts.first : widget.fallback!,
        initialZoom: pts.length == 1 ? 15 : 12,
        initialCameraFit: pts.length > 1
            ? fm.CameraFit.coordinates(coordinates: pts, padding: const EdgeInsets.all(48), maxZoom: 16)
            : null,
        interactionOptions: const fm.InteractionOptions(flags: fm.InteractiveFlag.all & ~fm.InteractiveFlag.rotate),
      ),
      children: [
        fm.TileLayer(
          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          userAgentPackageName: 'com.daliliai.travelplanner',
          tileBuilder: context.dark ? fm.darkModeTileBuilder : null,
        ),
        if (pts.length > 1)
          fm.PolylineLayer(polylines: [
            fm.Polyline(points: pts, color: DC.teal, strokeWidth: 3.5, pattern: fm.StrokePattern.dotted(spacingFactor: 1.6)),
          ]),
        fm.MarkerLayer(markers: [
          for (final (i, (p, it)) in widget.stops.indexed)
            fm.Marker(
              point: p,
              width: 36,
              height: 36,
              child: GestureDetector(
                onTap: () => _go(i),
                child: AnimatedScale(
                  scale: _focus == i ? 1.25 : 1,
                  duration: const Duration(milliseconds: 200),
                  child: Container(
                    decoration: BoxDecoration(
                      color: kindColor['${it['kind']}'] ?? DC.teal,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2.5),
                      boxShadow: const [BoxShadow(color: Colors.black38, blurRadius: 6, offset: Offset(0, 2))],
                    ),
                    alignment: Alignment.center,
                    child: Text('${i + 1}', style: mono(size: 13, color: DC.onBrand, weight: FontWeight.w800)),
                  ),
                ),
              ),
            ),
        ]),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final mapBox = ClipRRect(
      borderRadius: BorderRadius.circular(widget.full ? 0 : 22),
      child: Stack(children: [
        Positioned.fill(child: _mapView(context)),
        PositionedDirectional(
          end: 8,
          bottom: 6,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(color: Colors.white.withValues(alpha: .8), borderRadius: BorderRadius.circular(6)),
            child: const Text('© OpenStreetMap', style: TextStyle(fontSize: 10, color: Colors.black87)),
          ),
        ),
        if (!widget.full)
          PositionedDirectional(
            top: 8,
            end: 8,
            child: IconButton.filledTonal(
              tooltip: L('Full screen', 'ملء الشاشة'),
              onPressed: () => Navigator.of(context).push(passRoute(_FullMap(stops: widget.stops, fallback: widget.fallback))),
              icon: const Icon(Icons.open_in_full_rounded),
            ),
          ),
      ]),
    );
    if (widget.full) return mapBox;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SizedBox(height: 380, child: mapBox),
      const SizedBox(height: 10),
      for (final (i, (_, it)) in widget.stops.indexed)
        InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () => _go(i),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
              child: Row(children: [
                Container(
                  width: 28,
                  height: 28,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(color: (kindColor['${it['kind']}'] ?? DC.teal).withValues(alpha: .2), shape: BoxShape.circle),
                  child: Text('${i + 1}', style: mono(size: 12, color: context.ink)),
                ),
                const SizedBox(width: 10),
                Expanded(child: Text('${it['title'] ?? ''}', maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontWeight: _focus == i ? FontWeight.w800 : FontWeight.w600))),
                Text('${it['start'] ?? ''}', style: mono(size: 12, color: context.faint)),
              ]),
            ),
          ),
        ),
    ]);
  }
}

class _FullMap extends StatelessWidget {
  const _FullMap({required this.stops, this.fallback});
  final List<(LatLng, Map<String, dynamic>)> stops;
  final LatLng? fallback;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Stack(children: [
          Positioned.fill(child: _DayMap(stops: stops, fallback: fallback, full: true)),
          PositionedDirectional(
            top: MediaQuery.paddingOf(context).top + 8,
            start: 8,
            child: IconButton.filled(
              style: IconButton.styleFrom(backgroundColor: context.card, foregroundColor: context.ink),
              tooltip: MaterialLocalizations.of(context).closeButtonTooltip,
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.close_rounded),
            ),
          ),
        ]),
      );
}

// ---------------------------------------------------------------- sheets: what-if, rating
/// The budget slider: re-plans a copy with more or less money, shows what would change, and saves exactly that
/// version on Apply (as the website does).
class _WhatIfSheet extends StatefulWidget {
  const _WhatIfSheet({required this.state});
  final AppState state;

  @override
  State<_WhatIfSheet> createState() => _WhatIfSheetState();
}

class _WhatIfSheetState extends State<_WhatIfSheet> {
  double _delta = 0;
  bool _running = false;
  Map<String, dynamic>? _result;
  String? _error;

  AppState get st => widget.state;
  Map<String, dynamic> get _budget => asMap(asMap(st.trip?['trip_contract'])?['budget']) ?? const {};

  String _fail(Object e) => e is ApiException && e.status == 429
      ? tr('errRate', [60])
      : L('Couldn\'t re-plan with that budget - please try again.', 'معرفتش أعيد التخطيط بالميزانية دي - جرّب تاني.');

  Future<void> _run({bool apply = false}) async {
    final id = st.tripId;
    if (id == null || _delta == 0 || _running) return;
    if (st.busy) return toast(context, tr('busyWait'));
    setState(() {
      _running = true;
      _error = null;
    });
    try {
      final r = await st.api.post('/api/trips/$id/whatif', {'budget_delta': _delta, 'apply': apply}, const Duration(minutes: 5));
      if (apply) {
        await st.openTrip(id);
        if (!mounted) return;
        final b = _budget;
        Navigator.of(context).pop();
        toast(context, L('Budget updated to ${money(b['amount'] as num?, b['currency'] as String?)} - every plan was recalculated.',
            'الميزانية بقت ${money(b['amount'] as num?, b['currency'] as String?)} وكل الخطط اتحسبت من جديد.'));
        return;
      }
      if (mounted) setState(() => _result = asMap(r));
    } catch (e) {
      if (mounted) setState(() => _error = _fail(e));
    }
    if (mounted) setState(() => _running = false);
  }

  @override
  Widget build(BuildContext context) {
    final amount = (_budget['amount'] as num?) ?? 0;
    final cur = _budget['currency'] as String?;
    final step = whatIfStep(amount);
    final mode = '${st.trip?['selected_mode'] ?? 'balanced'}';
    final before = asMap(asMap(_result?['before'])?[mode]);
    final after = asMap(asMap(_result?['after'])?[mode]);
    final changes = (_result?['changes'] as List? ?? const []).map((e) => '$e').toList();
    final sign = _delta >= 0 ? '+' : '−';
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(L('WHAT IF', 'ماذا لو'), style: mono(size: 11, spacing: 2, color: DC.amber)),
          Text(L('Change the budget', 'غيّر الميزانية'), style: display(size: 22, color: context.ink)),
          const SizedBox(height: 4),
          Text(L('Plans are recomputed on a copy - nothing changes until you apply.',
              'الخطط بتتحسب على نسخة - مفيش حاجة بتتغير غير لما توافق.'), style: TextStyle(color: context.muted, fontSize: 13)),
          const SizedBox(height: 18),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: AlignmentDirectional.centerStart,
                child: Text(money(amount + _delta, cur), style: display(size: 30, color: context.ink)),
              ),
            ),
            Pill('$sign${money(_delta.abs(), cur)}', color: _delta >= 0 ? DC.green : DC.rose),
          ]),
          Slider(
            value: _delta,
            min: -10 * step,
            max: 10 * step,
            divisions: 20,
            label: '$sign${money(_delta.abs(), cur)}',
            onChanged: _running
                ? null
                : (v) => setState(() {
                      _delta = v;
                      _result = null; // Apply must save the version that was compared
                      _error = null;
                    }),
          ),
          const SizedBox(height: 6),
          BrandButton(
            label: L('Compare', 'قارن'),
            icon: Icons.compare_arrows_rounded,
            busy: _running && _result == null,
            onTap: _delta == 0 || _running ? null : _run,
          ),
          if (_running && _result == null) ...[
            const SizedBox(height: 10),
            Text(L('Re-planning on a copy… this can take a minute.', 'بعيد التخطيط على نسخة… ممكن ياخد دقيقة.'),
                textAlign: TextAlign.center, style: TextStyle(color: context.muted, fontSize: 12.5)),
          ],
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!, textAlign: TextAlign.center, style: const TextStyle(color: DC.rose, fontWeight: FontWeight.w700)),
          ],
          if (_result != null && before != null && after != null) ...[
            const SizedBox(height: 16),
            _Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr('mode.$mode'), style: display(size: 16, color: DC.mode[mode] ?? DC.teal)),
                const SizedBox(height: 6),
                Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, runSpacing: 4, children: [
                  Text(money(before['total'] as num?, (before['currency'] as String?) ?? cur),
                      style: TextStyle(color: context.muted, decoration: TextDecoration.lineThrough)),
                  Icon(isArabic ? Icons.arrow_back_rounded : Icons.arrow_forward_rounded, size: 16, color: context.faint),
                  Text(money(after['total'] as num?, (after['currency'] as String?) ?? cur), style: display(size: 20, color: context.ink)),
                ]),
                if (before['score'] != null || after['score'] != null)
                  Text('${tr('tripScore')} ${before['score'] ?? '–'} → ${after['score'] ?? '–'}',
                      style: TextStyle(fontWeight: FontWeight.w700, color: context.muted)),
                const SizedBox(height: 8),
                if (changes.isEmpty)
                  Text(L('No changes to the itinerary.', 'مفيش تغيير في البرنامج.'), style: TextStyle(color: context.muted))
                else
                  for (final c in changes.take(10))
                    Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Text('• $c', style: TextStyle(fontSize: 12.5, color: context.muted, height: 1.35)),
                    ),
              ]),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 52,
              child: FilledButton.icon(
                onPressed: _running ? null : () => _run(apply: true),
                icon: _running
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.check_rounded),
                label: Text(L('Apply this budget', 'طبّق الميزانية دي')),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}

const _rateDims = ['relevance', 'personalization', 'trust', 'explanations', 'itinerary', 'usability', 'confidence', 'overall'];

String _rateLabel(String d) => switch (d) {
      'relevance' => L('Fits what I asked', 'مناسبة للي طلبته'),
      'personalization' => L('Feels made for me', 'حاسس إنها معمولة ليا'),
      'trust' => L('I trust the prices and facts', 'واثق في الأسعار والمعلومات'),
      'explanations' => L('The reasons make sense', 'الأسباب منطقية'),
      'itinerary' => L('The days are well planned', 'الأيام متخططة كويس'),
      'usability' => L('Easy to use', 'سهل الاستخدام'),
      'confidence' => L('I\'d use this plan', 'هستخدم الخطة دي'),
      _ => L('Overall', 'التقييم العام'),
    };

/// Anonymous 1-5 ratings of the plan (the same questions as the website's).
class _RateSheet extends StatefulWidget {
  const _RateSheet({required this.state});
  final AppState state;

  @override
  State<_RateSheet> createState() => _RateSheetState();
}

class _RateSheetState extends State<_RateSheet> {
  final Map<String, int> _r = {};
  final _comment = TextEditingController();
  bool _sending = false;

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    setState(() => _sending = true);
    try {
      await widget.state.api.post('/api/evaluations',
          {'trip_id': widget.state.tripId, 'ratings': _r, 'comment': _comment.text.trim()});
      if (!mounted) return;
      Navigator.of(context).pop();
      toast(context, L('Thank you!', 'شكرًا!'));
    } catch (_) {
      if (!mounted) return;
      setState(() => _sending = false);
      toast(context, L('Could not save - please try again.', 'معرفناش نحفظ - جرّب تاني.'));
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(L('RATE THIS PLAN', 'قيّم الخطة'), style: mono(size: 11, spacing: 2, color: DC.rose)),
            Text(L('How good is this plan?', 'الخطة دي كويسة قد إيه؟'), style: display(size: 22, color: context.ink)),
            const SizedBox(height: 4),
            Text(L('Anonymous - it helps us measure and improve Dalili.', 'التقييم مجهول - بيساعدنا نقيس ونحسّن دليلي.'),
                style: TextStyle(color: context.muted, fontSize: 13)),
            const SizedBox(height: 12),
            for (final d in _rateDims) ...[
              const SizedBox(height: 10),
              Text(_rateLabel(d), style: const TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              Row(children: [
                for (var v = 1; v <= 5; v++)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 3),
                      child: Pressable(
                        onTap: () => setState(() => _r[d] = v),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 180),
                          height: 44,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            gradient: (_r[d] ?? 0) >= v ? DC.sunset : null,
                            color: (_r[d] ?? 0) >= v ? null : context.card2,
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: context.line),
                          ),
                          child: Text('$v', style: mono(size: 15, color: (_r[d] ?? 0) >= v ? DC.onBrand : context.ink)),
                        ),
                      ),
                    ),
                  ),
              ]),
            ],
            const SizedBox(height: 16),
            TextField(
              controller: _comment,
              maxLength: 1000,
              minLines: 2,
              maxLines: 4,
              decoration: InputDecoration(hintText: L('Anything to add? (optional)', 'عايز تضيف حاجة؟ (اختياري)')),
            ),
            const SizedBox(height: 8),
            BrandButton(
              label: L('Send rating', 'ابعت التقييم'),
              icon: Icons.send_rounded,
              busy: _sending,
              onTap: _r.length == _rateDims.length ? _send : null,
            ),
          ]),
        ),
      );
}
