import 'package:flutter/material.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../widgets/common.dart';
import 'trip_screen.dart';
import 'wizard_screen.dart';

class TripsScreen extends StatefulWidget {
  const TripsScreen({super.key, required this.state});
  final AppState state;
  @override
  State<TripsScreen> createState() => _TripsScreenState();
}

class _TripsScreenState extends State<TripsScreen> {
  String filter = 'all';

  List<Map<String, dynamic>> _filtered() {
    final today = DateTime.now().toIso8601String().substring(0, 10);
    final all = widget.state.trips.cast<Map<String, dynamic>>();
    return switch (filter) {
      'upcoming' => all.where((t) => t['status'] == 'planned' && '${t['start_date'] ?? ''}'.compareTo(today) >= 0).toList(),
      'past' => all.where((t) => t['status'] == 'planned' && '${t['end_date'] ?? '9'}'.compareTo(today) < 0).toList(),
      'drafts' => all.where((t) => t['status'] != 'planned').toList(),
      _ => all.toList(),
    };
  }

  Future<void> _open(Map<String, dynamic> t) async {
    final st = widget.state;
    final ok = await st.openTrip(t['trip_id'] as String);
    if (!mounted || !ok) return;
    if (st.plan != null) {
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => TripScreen(state: st)));
    } else {
      st.goTab(1);
    }
  }

  Future<bool> _confirmDelete() async =>
      await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(tr('deleteQ')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: Text(tr('cancel'))),
            FilledButton(style: FilledButton.styleFrom(backgroundColor: DC.rose, foregroundColor: Colors.white, minimumSize: const Size(80, 44)),
                onPressed: () => Navigator.pop(c, true), child: Text(tr('delete'))),
          ],
        ),
      ) ??
      false;

  @override
  Widget build(BuildContext context) {
    final list = _filtered();
    return Scaffold(
      appBar: AppBar(title: Text(tr('tripsTitle'))),
      body: RefreshIndicator(
        onRefresh: widget.state.refreshHome,
        child: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          SizedBox(
            height: 48,
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              scrollDirection: Axis.horizontal,
              children: [
                for (final f in ['all', 'upcoming', 'past', 'drafts'])
                  Padding(
                    padding: const EdgeInsetsDirectional.only(end: 8),
                    child: ChoiceChip(label: Text(tr(f)), selected: filter == f, onSelected: (_) => setState(() => filter = f)),
                  ),
              ],
            ),
          ),
          if (list.isEmpty)
            EmptyState(
              emoji: '🧳', title: tr('noTrips'), subtitle: tr('noTripsSub'), action: tr('planNew'),
              onAction: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => WizardScreen(state: widget.state))),
            )
          else
            for (final t in list)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
                child: Dismissible(
                  key: ValueKey(t['trip_id']),
                  direction: DismissDirection.endToStart,
                  confirmDismiss: (_) => _confirmDelete(),
                  onDismissed: (_) async {
                    try {
                      await widget.state.deleteTrip(t['trip_id'] as String);
                      if (context.mounted) toast(context, tr('deleted'));
                    } catch (_) {
                      widget.state.refreshHome();
                    }
                  },
                  background: Container(
                    decoration: BoxDecoration(color: DC.rose, borderRadius: BorderRadius.circular(20)),
                    alignment: AlignmentDirectional.centerEnd,
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: const Icon(Icons.delete_rounded, color: Colors.white),
                  ),
                  child: _TripCard(t: t, onTap: () => _open(t)),
                ),
              ),
        ]),
      ),
    );
  }
}

class _TripCard extends StatelessWidget {
  const _TripCard({required this.t, required this.onTap});
  final Map<String, dynamic> t;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final cities = (t['cities'] as List?) ?? [];
    final status = t['status'] as String? ?? 'collecting';
    final color = {'planned': DC.green, 'needs_input': DC.amber, 'error': DC.rose}[status] ?? DC.violet;
    final cur = t['currency'] as String?;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Row(children: [
          SizedBox(width: 100, height: 104, child: PlacePhoto(title: cities.isNotEmpty ? '${cities.first}' : null, emoji: '🧳')),
          const SizedBox(width: 14),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(cities.isEmpty ? '…' : routeText(cities), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleMedium),
                if (t['start_date'] != null)
                  Text('${fmtDate(t['start_date'] as String?)} – ${fmtDate(t['end_date'] as String?, year: true)}',
                      style: TextStyle(color: context.muted, fontSize: 12.5)),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  Pill(tr('st.$status'), color: color),
                  if (t['total'] != null) Text(money(t['total'] as num?, cur), style: const TextStyle(fontWeight: FontWeight.w800)),
                  if (t['score'] != null) Text('· ${t['score']}', style: TextStyle(color: context.muted, fontWeight: FontWeight.w700)),
                ]),
              ]),
            ),
          ),
          Padding(padding: const EdgeInsets.all(8), child: Icon(isArabic ? Icons.chevron_left : Icons.chevron_right, color: context.faint)),
        ]),
      ),
    );
  }
}
