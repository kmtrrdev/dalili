import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../widgets/common.dart';

/// "Suggest for me": real trips (fares + hotel prices from the traveller's airport) that fit the budget.
class IdeasScreen extends StatefulWidget {
  const IdeasScreen({super.key, required this.state, required this.body});
  final AppState state;
  final Map<String, dynamic> body;
  @override
  State<IdeasScreen> createState() => _IdeasScreenState();
}

class _IdeasScreenState extends State<IdeasScreen> {
  late Future<Map<String, dynamic>> _future = _load();

  Future<Map<String, dynamic>> _load() async =>
      await widget.state.api.post('/api/suggest', widget.body, const Duration(minutes: 3)) as Map<String, dynamic>;

  void _plan(Map<String, dynamic> idea) {
    final b = widget.body;
    final n = b['travelers'] as int;
    final msg = isArabic
        ? 'عايز أخطط رحلة إلى ${idea['name']} من ${b['origin']}، من ${idea['start_date']} لـ ${idea['end_date']}، عدد المسافرين $n، وميزانيتي ${b['budget'].round()} ${b['currency']}.'
        : 'Plan a trip to ${idea['name']} from ${b['origin']}, from ${idea['start_date']} to ${idea['end_date']}, $n traveller${n > 1 ? 's' : ''}, budget ${b['budget'].round()} ${b['currency']}.';
    final st = widget.state;
    st.logActivity('like', idea['name'] as String);
    st.newTrip();
    st.goTab(1);
    Navigator.of(context).pop();
    st.send(msg);
  }

  @override
  Widget build(BuildContext context) {
    final cur = widget.body['currency'] as String;
    return Scaffold(
      appBar: AppBar(title: Text(tr('ideasTitle'))),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, s) {
          if (s.connectionState != ConnectionState.done) {
            return Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const CircularProgressIndicator(color: DC.teal),
                const SizedBox(height: 18),
                Text(tr('ideasLoading'), style: TextStyle(color: context.muted)),
              ]),
            );
          }
          if (s.hasError) {
            final e = s.error;
            return EmptyState(emoji: '📡', title: e is ApiException && e.status == 0 ? tr('errNet') : '${e is ApiException ? e.message : e}',
                action: tr('next'), onAction: () => setState(() => _future = _load()));
          }
          final ideas = (s.data!['ideas'] as List?) ?? [];
          if (ideas.isEmpty) return EmptyState(emoji: '🧭', title: tr('noIdeas'));
          return ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            itemCount: ideas.length,
            separatorBuilder: (_, _) => const SizedBox(height: 12),
            itemBuilder: (_, i) => _IdeaCard(idea: ideas[i] as Map<String, dynamic>, cur: cur, onTap: () => _plan(ideas[i] as Map<String, dynamic>)),
          );
        },
      ),
    );
  }
}

class _IdeaCard extends StatelessWidget {
  const _IdeaCard({required this.idea, required this.cur, required this.onTap});
  final Map<String, dynamic> idea;
  final String cur;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final fit = idea['fit'] as String? ?? 'tight';
    final color = {'comfortable': DC.green, 'tight': DC.amber, 'over': DC.rose}[fit]!;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SizedBox(
            height: 150,
            child: Stack(fit: StackFit.expand, children: [
              PlacePhoto(url: idea['thumbnail'] as String?, title: idea['thumbnail'] == null ? idea['name'] as String : null),
              const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(
                  colors: [Colors.transparent, Color(0xB3000000)], begin: Alignment.center, end: Alignment.bottomCenter))),
              Positioned(top: 10, left: 10, child: Pill(tr('fit.$fit'), color: color, solid: true)),
              Positioned(
                left: 14, right: 14, bottom: 12,
                child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(idea['name'] as String, style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800)),
                      Text('${idea['country'] ?? ''} · ${tr('nights', [idea['nights']])}',
                          style: const TextStyle(color: Colors.white70, fontSize: 12.5)),
                    ]),
                  ),
                  Text(money(idea['total'], cur), style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w900)),
                ]),
              ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${fmtDate(idea['start_date'] as String?)} – ${fmtDate(idea['end_date'] as String?, year: true)}',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Row(children: [
                const Icon(Icons.flight_rounded, size: 16, color: DC.teal),
                const SizedBox(width: 6),
                Text('${tr('flight')}: ${money(idea['flight_price'], cur)}'),
                const SizedBox(width: 16),
                const Icon(Icons.hotel_rounded, size: 16, color: DC.violet),
                const SizedBox(width: 6),
                Expanded(child: Text(idea['hotel_unknown'] == true ? tr('hotelUnknown') : '${tr('hotel')}: ${money(idea['hotel_price'], cur)}',
                    overflow: TextOverflow.ellipsis)),
              ]),
              if ((idea['left'] as num? ?? 0) > 0) ...[
                const SizedBox(height: 6),
                Text(tr('left', [money(idea['left'], cur)]), style: TextStyle(color: color, fontWeight: FontWeight.w700)),
              ],
            ]),
          ),
        ]),
      ),
    );
  }
}
