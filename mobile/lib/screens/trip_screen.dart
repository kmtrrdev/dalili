import 'package:flutter/material.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../widgets/common.dart';

const _modes = ['balanced', 'budget', 'comfort', 'experience'];
const _kindIcon = {
  'flight': Icons.flight_rounded, 'transfer': Icons.local_taxi_rounded, 'hotel': Icons.hotel_rounded,
  'meal': Icons.restaurant_rounded, 'activity': Icons.place_rounded, 'free': Icons.wb_sunny_outlined,
  'rest': Icons.bed_rounded, 'transit': Icons.directions_transit_rounded,
};
const _kindColor = {
  'flight': DC.sky, 'transfer': DC.amber, 'hotel': DC.violet, 'meal': Color(0xFFFF8A5C), 'activity': DC.teal,
  'free': DC.green, 'rest': DC.violet,
};

class TripScreen extends StatefulWidget {
  const TripScreen({super.key, required this.state});
  final AppState state;
  @override
  State<TripScreen> createState() => _TripScreenState();
}

class _TripScreenState extends State<TripScreen> {
  String? switching;

  @override
  void initState() {
    super.initState();
    widget.state.addListener(_refresh);
  }

  @override
  void dispose() {
    widget.state.removeListener(_refresh);
    super.dispose();
  }

  void _refresh() => mounted ? setState(() {}) : null;

  Future<void> _mode(String m) async {
    setState(() => switching = m);
    try {
      await widget.state.selectMode(m);
    } catch (_) {
      if (mounted) toast(context, tr('errNet'));
    }
    if (mounted) setState(() => switching = null);
  }

  @override
  Widget build(BuildContext context) {
    final st = widget.state;
    final trip = st.trip;
    final plan = st.plan;
    if (trip == null || plan == null) {
      return Scaffold(appBar: AppBar(), body: EmptyState(emoji: '🗺️', title: tr('noPlanYet')));
    }
    final c = trip['trip_contract'] as Map<String, dynamic>;
    final stops = (c['stops'] as List?) ?? [];
    final cities = stops.isNotEmpty ? stops.map((s) => (s['ref'] as Map)['name']).toList() : [c['destination_name'] ?? c['destination']];
    final b = plan['budget'] as Map<String, dynamic>? ?? {};
    final score = (plan['score'] as Map?)?['total'] as num?;
    final pax = c['travelers'] as int? ?? 1;
    final days = (plan['days'] as List).cast<Map<String, dynamic>>();

    return DefaultTabController(
      length: 4,
      child: Scaffold(
        body: NestedScrollView(
          headerSliverBuilder: (context, _) => [
            SliverAppBar(
              pinned: true,
              expandedHeight: 250,
              foregroundColor: Colors.white,
              backgroundColor: context.dark ? DC.night : const Color(0xFF0E2A3A),
              flexibleSpace: FlexibleSpaceBar(
                titlePadding: const EdgeInsetsDirectional.only(start: 56, bottom: 14, end: 16),
                title: Text(routeText(cities), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 18)),
                background: Stack(fit: StackFit.expand, children: [
                  PlacePhoto(title: '${cities.first}'),
                  const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(
                      colors: [Color(0x66000000), Colors.transparent, Color(0xDD000000)],
                      begin: Alignment.topCenter, end: Alignment.bottomCenter))),
                  Positioned(
                    left: 16, right: 16, bottom: 46,
                    child: Text(
                      '${fmtDate(c['start_date'])} – ${fmtDate(c['end_date'], year: true)} · '
                      '${pax == 1 ? tr('travellers1') : tr('travellersN', [pax])} · ${c['origin_city'] ?? ''}',
                      style: const TextStyle(color: Colors.white70, fontWeight: FontWeight.w600),
                    ),
                  ),
                ]),
              ),
            ),
            SliverToBoxAdapter(child: _Summary(b: b, score: score)),
            SliverToBoxAdapter(
              child: SizedBox(
                height: 50,
                child: ListView(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  scrollDirection: Axis.horizontal,
                  children: [
                    for (final m in _modes)
                      if ((trip['plans'] as Map).containsKey(m))
                        Padding(
                          padding: const EdgeInsetsDirectional.only(end: 8),
                          child: ChoiceChip(
                            avatar: switching == m ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)) : null,
                            label: Text(tr('mode.$m')),
                            selected: trip['selected_mode'] == m,
                            onSelected: switching == null ? (_) => _mode(m) : null,
                          ),
                        ),
                  ],
                ),
              ),
            ),
            if (((isArabic ? plan['pitch_ar'] : null) ?? plan['pitch'] ?? '').toString().isNotEmpty)
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 2, 16, 8),
                  child: Text(((isArabic ? plan['pitch_ar'] : null) ?? plan['pitch']).toString(),
                      style: TextStyle(fontSize: 13, color: context.muted)),
                ),
              ),
            SliverPersistentHeader(
              pinned: true,
              delegate: _TabsHeader(TabBar(
                isScrollable: true,
                tabAlignment: TabAlignment.start,
                indicatorColor: DC.teal,
                labelStyle: const TextStyle(fontWeight: FontWeight.w800),
                tabs: [Tab(text: tr('tabPlan')), Tab(text: tr('tabStay')), Tab(text: tr('tabBudget')), Tab(text: tr('tabWeather'))],
              ), context.dark ? DC.night : DC.day),
            ),
          ],
          body: TabBarView(children: [
            _PlanTab(days: days, cur: b['currency'] as String? ?? 'USD'),
            _StayTab(plan: plan, pax: pax),
            _BudgetTab(b: b),
            _WeatherTab(days: days),
          ]),
        ),
        floatingActionButton: FloatingActionButton.extended(
          backgroundColor: DC.teal,
          foregroundColor: const Color(0xFF04110F),
          onPressed: () {
            st.goTab(1);
            Navigator.of(context).popUntil((r) => r.isFirst);
          },
          icon: const Icon(Icons.chat_bubble_rounded),
          label: Text(tr('askChange'), style: const TextStyle(fontWeight: FontWeight.w800)),
        ),
      ),
    );
  }
}

class _TabsHeader extends SliverPersistentHeaderDelegate {
  _TabsHeader(this.tabs, this.bg);
  final TabBar tabs;
  final Color bg;
  @override
  double get minExtent => tabs.preferredSize.height;
  @override
  double get maxExtent => tabs.preferredSize.height;
  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlapsContent) => Container(color: bg, child: tabs);
  @override
  bool shouldRebuild(covariant _TabsHeader old) => old.bg != bg || old.tabs != tabs;
}

class _Summary extends StatelessWidget {
  const _Summary({required this.b, required this.score});
  final Map<String, dynamic> b;
  final num? score;
  @override
  Widget build(BuildContext context) {
    final total = (b['total'] as num?) ?? 0, limit = (b['limit'] as num?) ?? 0;
    final ratio = limit > 0 ? (total / limit).clamp(0.0, 1.0).toDouble() : 0.0;
    final over = limit > 0 && total > limit;
    final cur = b['currency'] as String?;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(money(total, cur), style: Theme.of(context).textTheme.headlineMedium),
                Text(tr('ofBudget', [money(limit, cur)]), style: TextStyle(color: context.muted)),
                const SizedBox(height: 10),
                ClipRRect(
                  borderRadius: BorderRadius.circular(9),
                  child: LinearProgressIndicator(value: ratio, minHeight: 9, backgroundColor: context.line,
                      color: over ? DC.rose : (ratio > .9 ? DC.amber : DC.teal)),
                ),
                const SizedBox(height: 6),
                Text(over ? tr('overBy', [money(total - limit, cur)]) : tr('remaining', [money(limit - total, cur)]),
                    style: TextStyle(color: over ? DC.rose : DC.green, fontWeight: FontWeight.w700, fontSize: 12.5)),
              ]),
            ),
            if (score != null) ...[
              const SizedBox(width: 16),
              SizedBox(
                width: 76, height: 76,
                child: Stack(alignment: Alignment.center, children: [
                  SizedBox.expand(child: CircularProgressIndicator(value: score! / 100, strokeWidth: 7,
                      backgroundColor: context.line, color: DC.teal, strokeCap: StrokeCap.round)),
                  Column(mainAxisSize: MainAxisSize.min, children: [
                    Text('$score', style: Theme.of(context).textTheme.titleLarge),
                    Text(tr('tripScore'), style: TextStyle(fontSize: 9, color: context.muted, fontWeight: FontWeight.w700)),
                  ]),
                ]),
              ),
            ],
          ]),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- plan: day by day
class _PlanTab extends StatefulWidget {
  const _PlanTab({required this.days, required this.cur});
  final List<Map<String, dynamic>> days;
  final String cur;
  @override
  State<_PlanTab> createState() => _PlanTabState();
}

class _PlanTabState extends State<_PlanTab> {
  int day = 0;
  @override
  Widget build(BuildContext context) {
    if (day >= widget.days.length) day = 0;
    final d = widget.days[day];
    final items = (d['items'] as List).cast<Map<String, dynamic>>();
    final w = d['weather'] as Map<String, dynamic>?;
    return ListView(padding: const EdgeInsets.only(bottom: 96), children: [
      SizedBox(
        height: 78,
        child: ListView.separated(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          scrollDirection: Axis.horizontal,
          itemCount: widget.days.length,
          separatorBuilder: (_, _) => const SizedBox(width: 8),
          itemBuilder: (_, i) {
            final on = i == day;
            final dt = DateTime.tryParse(widget.days[i]['date'] as String? ?? '');
            return InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: () => setState(() => day = i),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                width: 64,
                decoration: BoxDecoration(
                  gradient: on ? DC.brand : null,
                  color: on ? null : context.card,
                  borderRadius: BorderRadius.circular(16),
                  border: on ? null : Border.all(color: context.line),
                ),
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text(tr('day', [i + 1]), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700,
                      color: on ? const Color(0xFF04110F) : context.muted)),
                  Text(dt == null ? '' : '${dt.day}', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900,
                      color: on ? const Color(0xFF04110F) : null)),
                ]),
              ),
            );
          },
        ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 4),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(d['title'] as String? ?? '', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 4),
          Wrap(spacing: 8, runSpacing: 6, children: [
            Text(fmtDate(d['date'] as String?, year: true), style: TextStyle(color: context.muted)),
            if (w != null) Pill('${w['condition']} · ${(w['temp_min_c'] as num).round()}–${(w['temp_max_c'] as num).round()}°C', color: DC.sky),
            if ((d['walking_km'] as num? ?? 0) > 0) Pill('🚶 ${(d['walking_km'] as num).toStringAsFixed(1)} km', color: DC.green),
          ]),
        ]),
      ),
      for (var i = 0; i < items.length; i++) _TimelineItem(item: items[i], last: i == items.length - 1),
    ]);
  }
}

class _TimelineItem extends StatefulWidget {
  const _TimelineItem({required this.item, required this.last});
  final Map<String, dynamic> item;
  final bool last;
  @override
  State<_TimelineItem> createState() => _TimelineItemState();
}

class _TimelineItemState extends State<_TimelineItem> {
  bool open = false;
  @override
  Widget build(BuildContext context) {
    final it = widget.item;
    final kind = it['kind'] as String? ?? 'activity';
    final color = _kindColor[kind] ?? DC.teal;
    final cost = it['cost'] as Map<String, dynamic>?;
    final amount = (cost?['amount'] as num?) ?? 0;
    final est = cost?['price_type'] == 'estimated';
    final notes = (it['notes'] as String? ?? '').trim();
    final leg = it['transport_from_previous'] as Map<String, dynamic>?;
    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SizedBox(
          width: 64,
          child: Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Column(children: [
              Text(it['start'] as String? ?? '', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13)),
              Text(it['end'] as String? ?? '', style: TextStyle(color: context.faint, fontSize: 11)),
            ]),
          ),
        ),
        Column(children: [
          Container(width: 2, height: 14, color: context.line),
          Container(
            width: 34, height: 34,
            decoration: BoxDecoration(color: color.withValues(alpha: .16), shape: BoxShape.circle),
            child: Icon(_kindIcon[kind] ?? Icons.place_rounded, size: 18, color: color),
          ),
          if (!widget.last) Expanded(child: Container(width: 2, color: context.line)),
        ]),
        const SizedBox(width: 10),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(0, 8, 16, 8),
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: notes.isEmpty ? null : () => setState(() => open = !open),
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: context.card, borderRadius: BorderRadius.circular(16), border: Border.all(color: context.line)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if (leg != null && (leg['minutes'] as num? ?? 0) > 0)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Text('↳ ${leg['minutes']} min ${leg['mode'] ?? ''}', style: TextStyle(color: context.faint, fontSize: 11.5)),
                    ),
                  Text(it['title'] as String? ?? '', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5, height: 1.3)),
                  if (amount > 0) ...[
                    const SizedBox(height: 6),
                    Row(children: [
                      Text('${est ? '≈ ' : ''}${money(amount, cost?['currency'] as String?)}',
                          style: const TextStyle(fontWeight: FontWeight.w800)),
                      const SizedBox(width: 6),
                      Pill(est ? tr('est') : '✓', color: est ? DC.violet : DC.green),
                    ]),
                  ],
                  if (notes.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(notes, maxLines: open ? 20 : 2, overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: context.muted, fontSize: 12.5, height: 1.35)),
                  ],
                ]),
              ),
            ),
          ),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------------- flights + hotel
class _StayTab extends StatelessWidget {
  const _StayTab({required this.plan, required this.pax});
  final Map<String, dynamic> plan;
  final int pax;

  @override
  Widget build(BuildContext context) {
    final flights = <(String, Map<String, dynamic>)>[
      if (plan['outbound_flight'] != null) (tr('outbound'), plan['outbound_flight'] as Map<String, dynamic>),
      for (final l in (plan['legs'] as List? ?? [])) ('✈', l as Map<String, dynamic>),
      if (plan['return_flight'] != null) (tr('return'), plan['return_flight'] as Map<String, dynamic>),
    ];
    final hotels = <Map<String, dynamic>>[
      if (plan['hotel'] != null) plan['hotel'] as Map<String, dynamic>,
      for (final s in (plan['stops'] as List? ?? [])) if ((s as Map)['hotel'] != null) s['hotel'] as Map<String, dynamic>,
    ];
    return ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 96), children: [
      for (final (label, f) in flights) ...[_FlightCard(label: label, f: f), const SizedBox(height: 12)],
      for (final h in hotels) ...[_HotelCard(h: h), const SizedBox(height: 12)],
      Text(tr('priceNote'), style: TextStyle(color: context.faint, fontSize: 12)),
    ]);
  }
}

String _hm(String? iso) {
  final d = DateTime.tryParse(iso ?? '');
  if (d == null) return '';
  final s = iso!.substring(11, 16); // local time as published by the airline
  return s.isNotEmpty ? s : '${d.hour}:${d.minute}';
}

class _FlightCard extends StatelessWidget {
  const _FlightCard({required this.label, required this.f});
  final String label;
  final Map<String, dynamic> f;
  @override
  Widget build(BuildContext context) {
    final mins = f['duration_minutes'] as int? ?? 0;
    final stops = f['stops'] as int? ?? 0;
    final price = f['price_per_person'] as Map<String, dynamic>?;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Pill(label, color: DC.sky),
            const SizedBox(width: 8),
            Expanded(child: Text('${f['airline'] ?? ''}', maxLines: 1, overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontWeight: FontWeight.w700))),
            Text(money(price?['amount'] as num?, price?['currency'] as String?), style: Theme.of(context).textTheme.titleMedium),
            Text(' ${tr('perPerson')}', style: TextStyle(color: context.muted, fontSize: 11)),
          ]),
          const SizedBox(height: 16),
          Row(children: [
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(_hm(f['depart_at'] as String?), style: Theme.of(context).textTheme.headlineMedium),
              Text('${f['origin']}', style: TextStyle(color: context.muted, fontWeight: FontWeight.w700)),
            ]),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Column(children: [
                  Text('${mins ~/ 60}h${(mins % 60).toString().padLeft(2, '0')}', style: TextStyle(color: context.muted, fontSize: 12)),
                  Row(children: [
                    Expanded(child: Divider(color: DC.teal.withValues(alpha: .6), thickness: 1.5)),
                    Transform.rotate(angle: isArabic ? -1.5708 : 1.5708, child: const Icon(Icons.flight_rounded, color: DC.teal, size: 18)),
                    Expanded(child: Divider(color: DC.teal.withValues(alpha: .6), thickness: 1.5)),
                  ]),
                  Text(stops == 0 ? tr('direct') : '${tr('stopsN', [stops])}${f['via'] != null ? ' · ${f['via']}' : ''}',
                      style: TextStyle(color: stops == 0 ? DC.green : context.muted, fontSize: 12, fontWeight: FontWeight.w600)),
                ]),
              ),
            ),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(_hm(f['arrive_at'] as String?), style: Theme.of(context).textTheme.headlineMedium),
              Text('${f['destination']}', style: TextStyle(color: context.muted, fontWeight: FontWeight.w700)),
            ]),
          ]),
          const SizedBox(height: 8),
          Text('${f['flight_number'] ?? ''} · ${fmtDate(f['depart_at'] as String?)}', style: TextStyle(color: context.faint, fontSize: 12)),
          if (f['booking_url'] != null) ...[
            const SizedBox(height: 12),
            SizedBox(width: double.infinity, child: OutlinedButton.icon(
              onPressed: () => openLink(f['booking_url'] as String), icon: const Icon(Icons.open_in_new_rounded, size: 18), label: Text(tr('book')))),
          ],
        ]),
      ),
    );
  }
}

class _HotelCard extends StatelessWidget {
  const _HotelCard({required this.h});
  final Map<String, dynamic> h;
  @override
  Widget build(BuildContext context) {
    final images = (h['images'] as List? ?? []).cast<String>();
    final night = h['price_per_night'] as Map<String, dynamic>?;
    final total = h['total_price'] as Map<String, dynamic>?;
    final stars = h['stars'] as int?;
    final google = 'https://www.google.com/travel/search?q=${Uri.encodeComponent('${h['name']}')}';
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (images.isNotEmpty)
          SizedBox(
            height: 170,
            child: PageView(children: [for (final u in images.take(6)) PlacePhoto(url: u, emoji: '🏨', tint: DC.violet)]),
          ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text('${h['name']}', style: Theme.of(context).textTheme.titleMedium)),
              if (stars != null) Text('★' * stars, style: const TextStyle(color: DC.amber)),
            ]),
            const SizedBox(height: 4),
            Wrap(spacing: 8, runSpacing: 6, children: [
              if (h['rating'] != null) Pill('⭐ ${h['rating']} · ${h['reviews_count'] ?? 0}', color: DC.amber),
              if (h['neighborhood'] != null) Pill('📍 ${h['neighborhood']}', color: DC.violet),
              if (h['breakfast_included'] == true) Pill('☕ ${tr('breakfast')}', color: DC.green),
            ]),
            const SizedBox(height: 12),
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(money(night?['amount'] as num?, night?['currency'] as String?), style: Theme.of(context).textTheme.headlineMedium),
              Text(' ${tr('perNight')}', style: TextStyle(color: context.muted)),
              const Spacer(),
              Text('${tr('stayTotal')}: ${money(total?['amount'] as num?, total?['currency'] as String?)}',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
            ]),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: FilledButton.icon(onPressed: () => openLink(google), icon: const Icon(Icons.hotel_rounded, size: 18), label: Text(tr('book')))),
              if (h['link'] != null) ...[
                const SizedBox(width: 8),
                OutlinedButton(onPressed: () => openLink(h['link'] as String), child: Text(tr('website'))),
              ],
              if (h['location'] != null) ...[
                const SizedBox(width: 8),
                IconButton.outlined(
                  onPressed: () => openLink('https://www.google.com/maps/search/?api=1&query=${h['location']['lat']},${h['location']['lon']}'),
                  icon: const Icon(Icons.map_outlined)),
              ],
            ]),
          ]),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------------- budget
class _BudgetTab extends StatelessWidget {
  const _BudgetTab({required this.b});
  final Map<String, dynamic> b;
  @override
  Widget build(BuildContext context) {
    final cur = b['currency'] as String?;
    final parts = [
      ('bFlights', 'flights', DC.sky, Icons.flight_rounded), ('bHotel', 'hotel', DC.violet, Icons.hotel_rounded),
      ('bFood', 'food', const Color(0xFFFF8A5C), Icons.restaurant_rounded), ('bActivities', 'activities', DC.teal, Icons.place_rounded),
      ('bTransport', 'transport', DC.amber, Icons.directions_bus_rounded), ('bBuffer', 'buffer', DC.green, Icons.savings_rounded),
    ];
    final total = (b['total'] as num?) ?? 1;
    final daily = (b['daily_spending'] as Map?)?.cast<String, dynamic>() ?? {};
    final maxDay = daily.values.fold<num>(1, (m, v) => (v as num) > m ? v : m);
    return ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 96), children: [
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(children: [
            for (final (label, key, color, icon) in parts)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Row(children: [
                  Container(width: 34, height: 34, decoration: BoxDecoration(color: color.withValues(alpha: .15), borderRadius: BorderRadius.circular(10)),
                      child: Icon(icon, size: 18, color: color)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Text(tr(label), style: const TextStyle(fontWeight: FontWeight.w700)),
                        const Spacer(),
                        Text(money(b[key] as num?, cur), style: const TextStyle(fontWeight: FontWeight.w800)),
                      ]),
                      const SizedBox(height: 6),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(6),
                        child: LinearProgressIndicator(value: (((b[key] as num?) ?? 0) / total).clamp(0.0, 1.0).toDouble(),
                            minHeight: 7, backgroundColor: context.line, color: color),
                      ),
                    ]),
                  ),
                ]),
              ),
          ]),
        ),
      ),
      if (daily.isNotEmpty) ...[
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              height: 150,
              child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                for (final e in daily.entries)
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 3),
                      child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                        Text(money(e.value as num, cur), style: TextStyle(fontSize: 9.5, color: context.muted)),
                        const SizedBox(height: 4),
                        Container(
                          height: 90 * ((e.value as num) / maxDay).toDouble() + 4,
                          decoration: BoxDecoration(gradient: DC.brand, borderRadius: BorderRadius.circular(6)),
                        ),
                        const SizedBox(height: 4),
                        Text(e.key.substring(8), style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
                      ]),
                    ),
                  ),
              ]),
            ),
          ),
        ),
      ],
      const SizedBox(height: 12),
      for (final n in (b['notes'] as List? ?? [])) Padding(padding: const EdgeInsets.only(bottom: 4),
          child: Text('• $n', style: TextStyle(color: context.muted, fontSize: 12.5))),
    ]);
  }
}

// ---------------------------------------------------------------- weather
class _WeatherTab extends StatelessWidget {
  const _WeatherTab({required this.days});
  final List<Map<String, dynamic>> days;
  IconData _icon(String c) {
    final s = c.toLowerCase();
    if (s.contains('thunder') || s.contains('storm')) return Icons.thunderstorm_rounded;
    if (s.contains('rain') || s.contains('drizzle') || s.contains('shower')) return Icons.water_drop_rounded;
    if (s.contains('snow')) return Icons.ac_unit_rounded;
    if (s.contains('clear') || s.contains('sun')) return Icons.wb_sunny_rounded;
    return Icons.cloud_rounded;
  }

  @override
  Widget build(BuildContext context) {
    final ws = days.map((d) => d['weather'] as Map<String, dynamic>?).whereType<Map<String, dynamic>>().toList();
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
      itemCount: ws.length,
      separatorBuilder: (_, _) => const SizedBox(height: 10),
      itemBuilder: (_, i) {
        final w = ws[i];
        final rain = w['precipitation_probability'] as num? ?? 0;
        return Card(
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            leading: Icon(_icon(w['condition'] as String? ?? ''), size: 32, color: rain > 40 ? DC.sky : DC.amber),
            title: Text(fmtDate(w['date'] as String?), style: const TextStyle(fontWeight: FontWeight.w800)),
            subtitle: Text('${w['condition']} · ${tr('rain', [rain])}'),
            trailing: Text('${(w['temp_max_c'] as num).round()}° / ${(w['temp_min_c'] as num).round()}°',
                style: Theme.of(context).textTheme.titleMedium),
          ),
        );
      },
    );
  }
}
