import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../core/api.dart';
import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';
import 'wizard_screen.dart' show passCode;

/// "Suggest for me": real trips (fares + hotel prices from the traveller's airport) that fit the budget, dealt out
/// as a deck of tickets to swipe through.
class IdeasScreen extends StatefulWidget {
  const IdeasScreen({super.key, required this.state, required this.body});
  final AppState state;
  final Map<String, dynamic> body;
  @override
  State<IdeasScreen> createState() => _IdeasScreenState();
}

class _IdeasScreenState extends State<IdeasScreen> {
  late Future<Map<String, dynamic>> _future = _load();
  final _pages = PageController(viewportFraction: .86);

  Future<Map<String, dynamic>> _load() async =>
      await widget.state.api.post('/api/suggest', widget.body, const Duration(minutes: 3)) as Map<String, dynamic>;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _plan(Map<String, dynamic> idea) {
    final b = widget.body;
    final n = b['travelers'] as int;
    final sd = idea['start_date'] as String?, ed = idea['end_date'] as String?;
    final month = b['month'] as int?, nights = idea['nights'];
    // Dates when the idea has them; otherwise the month and length asked for (never "from null to null").
    final monthName = month != null ? DateFormat.MMMM(isArabic ? 'ar' : 'en').format(DateTime(2000, month)) : null;
    final when = sd != null && ed != null
        ? (isArabic ? 'من $sd لـ $ed' : 'from $sd to $ed')
        : isArabic
            ? '${monthName != null ? 'في $monthName ' : ''}لمدة $nights ليالي'
            : '${monthName != null ? 'in $monthName ' : ''}for $nights nights';
    final wishes = prefsSuffix(occasion: b['occasion'] as String?, interests: ((b['interests'] as List?) ?? const []).cast<String>(),
        direct: b['direct_only'] == true, notes: (b['notes'] as String?) ?? '');
    final msg = isArabic
        ? 'عايز أخطط رحلة إلى ${idea['name']} من ${b['origin']}، $when، عدد المسافرين $n، وميزانيتي ${b['budget'].round()} ${b['currency']}.$wishes'
        : 'Plan a trip to ${idea['name']} from ${b['origin']}, $when, $n traveller${n > 1 ? 's' : ''}, budget ${b['budget'].round()} ${b['currency']}.$wishes';
    final st = widget.state;
    st.logActivity('like', idea['name'] as String);
    st.newTrip();
    st.goTab(Tabs.chat);
    Navigator.of(context).pop();
    st.send(msg);
  }

  @override
  Widget build(BuildContext context) {
    final cur = widget.body['currency'] as String;
    return Scaffold(
      body: SkyBackground(
        planes: 2,
        child: SafeArea(
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 4, 16, 4),
              child: Row(children: [
                const BackButton(),
                const SizedBox(width: 4),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text(L('TRIP IDEAS', 'أفكار رحلات'),
                        style: TextStyle(fontSize: 11, letterSpacing: 1.8, fontWeight: FontWeight.w800, color: context.faint)),
                    Text(tr('ideasTitle'), maxLines: 1, overflow: TextOverflow.ellipsis, style: display(size: 19, color: context.ink)),
                  ]),
                ),
              ]),
            ),
            Expanded(
              child: FutureBuilder<Map<String, dynamic>>(
                future: _future,
                builder: (context, s) {
                  if (s.connectionState != ConnectionState.done) {
                    return _DeparturesBoard(origin: '${widget.body['origin'] ?? ''}');
                  }
                  if (s.hasError) {
                    final e = s.error;
                    return Center(
                      child: SingleChildScrollView(
                        child: EmptyState(
                          emoji: '📡',
                          title: e is ApiException && e.status == 0 ? tr('errNet') : '${e is ApiException ? e.message : e}',
                          action: L('Try again', 'جرب تاني'),
                          onAction: () => setState(() => _future = _load()),
                        ),
                      ),
                    );
                  }
                  final data = s.data!;
                  final ideas = ((data['ideas'] as List?) ?? const []).whereType<Map<String, dynamic>>().toList();
                  if (ideas.isEmpty) {
                    return Center(child: SingleChildScrollView(child: EmptyState(emoji: '🧭', title: tr('noIdeas'))));
                  }
                  final origin = '${(data['origin'] as Map?)?['name'] ?? widget.body['origin'] ?? ''}';
                  return _deck(ideas, data, origin, cur);
                },
              ),
            ),
          ]),
        ),
      ),
    );
  }

  Widget _deck(List<Map<String, dynamic>> ideas, Map<String, dynamic> data, String origin, String cur) {
    final pax = widget.body['travelers'] as int? ?? 1;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 2, 16, 8),
        child: Wrap(spacing: 6, runSpacing: 6, alignment: WrapAlignment.center, children: [
          Pill('${passCode(origin)} · $origin', icon: Icons.flight_takeoff_rounded, color: DC.sky),
          Pill(money(widget.body['budget'] as num?, cur), icon: Icons.account_balance_wallet_outlined, color: DC.green),
          Pill(pax == 1 ? tr('travellers1') : tr('travellersN', [pax]), color: DC.violet),
          if (data['estimated'] == true) Pill(L('Estimated prices', 'أسعار تقديرية'), color: DC.amber),
          if (data['all_fit'] == false) Pill(L('Closest to your budget', 'الأقرب لميزانيتك'), color: DC.rose),
        ]),
      ),
      Expanded(
        child: PageView.builder(
          controller: _pages,
          itemCount: ideas.length,
          itemBuilder: (_, i) => Coverflow(
            controller: _pages,
            index: i,
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(6, 6, 6, 18),
              child: Tilt3D(
                maxAngle: .1,
                child: RepaintBoundary(
                  child: _IdeaTicket(idea: ideas[i], origin: origin, cur: cur, pax: pax, onPlan: () => _plan(ideas[i])),
                ),
              ),
            ),
          ),
        ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        child: ListenableBuilder(
          listenable: _pages,
          builder: (context, _) {
            final p = _pages.hasClients && _pages.position.haveDimensions ? (_pages.page ?? 0) : 0.0;
            final at = p.round().clamp(0, ideas.length - 1);
            return Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              Directionality(
                textDirection: TextDirection.ltr,
                child: Text('${(at + 1).toString().padLeft(2, '0')} / ${ideas.length.toString().padLeft(2, '0')}',
                    style: mono(size: 12, color: context.muted)),
              ),
              const SizedBox(width: 12),
              Flexible(
                child: Wrap(spacing: 4, children: [
                  for (var i = 0; i < ideas.length; i++)
                    AnimatedContainer(
                      duration: const Duration(milliseconds: 220),
                      width: i == at ? 18 : 6,
                      height: 6,
                      decoration: BoxDecoration(
                        color: i == at ? (context.dark ? DC.teal : DC.tealDeep) : context.faint.withValues(alpha: .4),
                        borderRadius: BorderRadius.circular(9),
                      ),
                    ),
                ]),
              ),
            ]);
          },
        ),
      ),
    ]);
  }
}

class _IdeaTicket extends StatelessWidget {
  const _IdeaTicket({required this.idea, required this.origin, required this.cur, required this.pax, required this.onPlan});
  final Map<String, dynamic> idea;
  final String origin, cur;
  final int pax;
  final VoidCallback onPlan;

  @override
  Widget build(BuildContext context) {
    final fit = idea['fit'] as String? ?? 'tight';
    final color = {'comfortable': DC.green, 'tight': DC.amber, 'over': DC.rose}[fit] ?? DC.amber;
    final name = '${idea['name'] ?? ''}';
    final country = '${idea['country'] ?? ''}';
    final nights = (idea['nights'] as num?)?.round() ?? 0;
    final flight = idea['flight_price'] as num?;
    final hotel = idea['hotel_price'] as num?;
    final total = idea['total'] as num?;
    final left = idea['left'] as num? ?? 0;
    final hotelUnknown = idea['hotel_unknown'] == true || hotel == null;
    // The total counts every room; what's left after the flights is the stay.
    final stay = !hotelUnknown && total != null && flight != null ? total - flight * pax : null;
    final match = (idea['score'] as num?)?.round();
    final why = '${idea['why'] ?? ''}'.trim();
    final stops = idea['stops'] as num?;
    final minutes = (idea['flight_minutes'] as num?)?.round();
    final flightInfo = [
      if ((idea['airline'] as String?)?.isNotEmpty == true) idea['airline'] as String,
      if (stops != null) stops == 0 ? tr('direct') : tr('stopsN', [stops]),
      if (minutes != null && minutes > 0) '${minutes ~/ 60}h ${(minutes % 60).toString().padLeft(2, '0')}m',
    ].join(' · ');
    final sd = idea['start_date'] as String?, ed = idea['end_date'] as String?;
    final accent = context.dark ? DC.teal : DC.tealDeep;

    Widget line(IconData icon, Color c, String label, String detail, String value) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(children: [
            Container(
              width: 32,
              height: 32,
              alignment: Alignment.center,
              decoration: BoxDecoration(color: c.withValues(alpha: .15), borderRadius: BorderRadius.circular(10)),
              child: Icon(icon, size: 17, color: c),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(label, style: TextStyle(fontWeight: FontWeight.w700, color: context.ink, fontSize: 13.5)),
                if (detail.isNotEmpty)
                  Text(detail, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 12)),
              ]),
            ),
            const SizedBox(width: 8),
            Text(value, style: mono(size: 14, color: context.ink)),
          ]),
        );

    return Ticket(
      main: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SizedBox(
          height: 168,
          child: Stack(fit: StackFit.expand, children: [
            PlacePhoto(url: idea['thumbnail'] as String?, title: idea['thumbnail'] == null ? name : null, tint: color),
            const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(
                colors: [Color(0x33000000), Colors.transparent, Color(0xC0000000)], stops: [0, .4, 1],
                begin: Alignment.topCenter, end: Alignment.bottomCenter))),
            PositionedDirectional(top: 12, start: 12, child: Pill(tr('fit.$fit'), color: color, solid: true)),
            if (match != null)
              PositionedDirectional(top: 12, end: 12, child: Pill(tr('match', [match]), color: DC.violet, solid: true)),
            PositionedDirectional(
              start: 16,
              end: 16,
              bottom: 12,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(name, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: display(size: 24, color: Colors.white, height: 1.1)),
                Text([if (country.isNotEmpty) country, tr('nights', [nights])].join(' · '),
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white70, fontSize: 12.5)),
              ]),
            ),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              _Code(code: passCode(origin), city: origin),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: FlyingRoute(color: accent, height: 40),
                ),
              ),
              _Code(code: passCode(name), city: name, end: true),
            ]),
            const SizedBox(height: 10),
            Row(children: [
              Expanded(child: PassField(tr('outbound'), sd == null ? '—' : fmtDate(sd))),
              Expanded(child: PassField(tr('return'), ed == null ? '—' : fmtDate(ed, year: true))),
              PassField(L('Nights', 'ليالي'), '$nights', end: true),
            ]),
            if (flightInfo.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(flightInfo, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 12)),
            ],
          ]),
        ),
      ]),
      stub: Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          line(Icons.flight_rounded, DC.sky, tr('flight'), flight == null ? '' : '${money(flight, cur)} ${tr('perPerson')} × $pax',
              money(flight == null ? null : flight * pax, cur)),
          line(Icons.hotel_rounded, DC.violet, tr('hotel'),
              hotelUnknown ? tr('hotelUnknown') : '${money(hotel, cur)} ${tr('perNight')} · ${tr('nights', [nights])}',
              hotelUnknown ? '–' : money(stay, cur)),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Divider(height: 1, color: context.line),
          ),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr('total').toUpperCase(),
                    style: TextStyle(fontSize: 10, letterSpacing: 1.2, fontWeight: FontWeight.w800, color: context.faint)),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: AlignmentDirectional.centerStart,
                  child: Text(money(total, cur), style: mono(size: 26, weight: FontWeight.w800, color: context.ink)),
                ),
              ]),
            ),
            if (left != 0)
              Flexible(
                child: Text(left > 0 ? tr('left', [money(left, cur)]) : tr('overBy', [money(-left, cur)]),
                    textAlign: TextAlign.end, maxLines: 2,
                    style: TextStyle(color: left > 0 ? color : DC.rose, fontWeight: FontWeight.w800, fontSize: 12.5)),
              ),
          ]),
          if (why.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(why, maxLines: 3, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 12.5, height: 1.4)),
          ],
          const SizedBox(height: 12),
          Barcode('$name$sd$ed$total', height: 30),
          const SizedBox(height: 14),
          BrandButton(label: L('Plan this trip', 'خطط الرحلة دي'), icon: Icons.flight_takeoff_rounded, onTap: onPlan),
        ]),
      ),
    );
  }
}

class _Code extends StatelessWidget {
  const _Code({required this.code, required this.city, this.end = false});
  final String code, city;
  final bool end;
  @override
  Widget build(BuildContext context) => ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 96),
        child: Column(crossAxisAlignment: end ? CrossAxisAlignment.end : CrossAxisAlignment.start, children: [
          Text(code, maxLines: 1, style: mono(size: 24, weight: FontWeight.w800, color: context.ink)),
          Text(city, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 11.5)),
        ]),
      );
}

/// While real fares are fetched: an airport departures board whose destinations keep flipping.
class _DeparturesBoard extends StatefulWidget {
  const _DeparturesBoard({required this.origin});
  final String origin;
  @override
  State<_DeparturesBoard> createState() => _DeparturesBoardState();
}

class _DeparturesBoardState extends State<_DeparturesBoard> {
  static const _cities = ['ISTANBUL', 'DUBAI', 'PARIS', 'ROME', 'ATHENS', 'LONDON', 'TBILISI', 'BAKU', 'MADRID', 'VIENNA',
    'PRAGUE', 'MALE', 'BALI', 'TOKYO', 'NAIROBI', 'MUSCAT', 'BEIRUT', 'AMMAN', 'ZANZIBAR', 'LISBON', 'BUDAPEST', 'PHUKET'];
  static const _times = ['06:40', '08:15', '09:50', '11:25', '13:05'];
  static const _gates = ['A12', 'B07', 'C21', 'D03', 'A04'];
  final _rows = [0, 4, 8, 12, 16];
  int _tick = 0;
  Timer? _t;

  @override
  void initState() {
    super.initState();
    // One row changes at a time, like a real board.
    _t = Timer.periodic(const Duration(milliseconds: 1400), (_) {
      if (!mounted) return;
      setState(() {
        _tick++;
        final r = _tick % _rows.length;
        _rows[r] = (_rows[r] + 5) % _cities.length;
      });
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const amber = Color(0xFFFFD27A);
    const tile = Color(0xFF151C2E);
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Float(
            amount: 3,
            child: Container(
              padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
              decoration: BoxDecoration(
                color: const Color(0xFF0A0F1C),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: Colors.white.withValues(alpha: .08)),
                boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .4), blurRadius: 30, offset: const Offset(0, 14))],
              ),
              child: Directionality(
                textDirection: TextDirection.ltr,
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(children: [
                    const Icon(Icons.flight_takeoff_rounded, color: amber, size: 18),
                    const SizedBox(width: 8),
                    Text('DEPARTURES', style: mono(size: 14, color: amber, spacing: 2)),
                    const Spacer(),
                    Text('FROM ${passCode(widget.origin)}', style: mono(size: 12, color: const Color(0xFF93A3C2))),
                  ]),
                  const SizedBox(height: 10),
                  for (var i = 0; i < _rows.length; i++)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Row(children: [
                          Text(_times[i], style: mono(size: 13, color: const Color(0xFF93A3C2))),
                          const SizedBox(width: 10),
                          SizedBox(
                            width: 158,
                            child: Align(
                              alignment: Alignment.centerLeft,
                              child: SplitFlap(_cities[_rows[i]].padRight(9), style: mono(size: 13, color: Colors.white), tileColor: tile),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Text(_gates[i], style: mono(size: 13, color: const Color(0xFF93A3C2))),
                          const SizedBox(width: 10),
                          AnimatedOpacity(
                            duration: const Duration(milliseconds: 500),
                            opacity: (_tick + i).isEven ? 1 : .35,
                            child: Text('CHECKING', style: mono(size: 12, color: amber)),
                          ),
                        ]),
                      ),
                    ),
                ]),
              ),
            ),
          ),
          const SizedBox(height: 22),
          SizedBox(
            width: 180,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(9),
              child: LinearProgressIndicator(minHeight: 4, color: context.dark ? DC.teal : DC.tealDeep, backgroundColor: context.line),
            ),
          ),
          const SizedBox(height: 14),
          Text(tr('ideasLoading'), textAlign: TextAlign.center, style: TextStyle(color: context.muted, fontWeight: FontWeight.w600)),
        ]),
      ),
    );
  }
}
