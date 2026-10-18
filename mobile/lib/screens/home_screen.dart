import 'package:flutter/material.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../widgets/common.dart';
import 'trip_screen.dart';
import 'wizard_screen.dart';

const _vibes = [
  ('beach', '🏖️', ['beach', 'relax'], null),
  ('city', '🏙️', ['culture', 'food', 'shopping'], null),
  ('history', '🏛️', ['history', 'culture'], null),
  ('honeymoon', '💍', ['relax', 'beach', 'food'], 'honeymoon'),
  ('family', '👨‍👩‍👧', ['nature', 'beach'], 'family'),
  ('snow', '⛷️', ['ski', 'nature'], null),
];

// name shown, Wikipedia page with a real photo
const _dests = [
  ('Istanbul', 'Istanbul'), ('Paris', 'Paris'), ('Rome', 'Rome'), ('Dubai', 'Dubai'), ('Santorini', 'Oia,_Greece'),
  ('Barcelona', 'Barcelona'), ('Marrakesh', 'Marrakesh'), ('Maldives', 'Tourism_in_the_Maldives'), ('Tokyo', 'Tokyo'),
  ('Sharm El Sheikh', 'Sharm_El_Sheikh'),
];

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.state});
  final AppState state;

  void _wizard(BuildContext context, WizardPrefill p) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => WizardScreen(state: state, prefill: p)));

  @override
  Widget build(BuildContext context) {
    final recs = state.recs;
    final items = (recs?['items'] as List?) ?? [];
    final plan = state.plan;
    return RefreshIndicator(
      onRefresh: state.refreshHome,
      child: CustomScrollView(slivers: [
        SliverSafeArea(
          bottom: false,
          sliver: SliverToBoxAdapter(child: _TopBar(state: state)),
        ),
        SliverToBoxAdapter(child: _Hero(state: state, onForm: () => _wizard(context, const WizardPrefill()))),
        if (plan != null) SliverToBoxAdapter(child: _ContinueCard(state: state)),
        if (items.isNotEmpty) ...[
          SliverToBoxAdapter(child: SectionHeader(tr('forYou'), subtitle: tr('forYouSub'))),
          SliverToBoxAdapter(
            child: SizedBox(
              height: 372,
              child: ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                scrollDirection: Axis.horizontal,
                itemCount: items.length,
                separatorBuilder: (_, _) => const SizedBox(width: 12),
                itemBuilder: (_, i) => RecCard(
                  rec: items[i] as Map<String, dynamic>,
                  onPlan: (city) {
                    state.logActivity('like', city);
                    _wizard(context, WizardPrefill(stops: [city]));
                  },
                  onDismiss: (city) {
                    state.logActivity('dismiss', city);
                    toast(context, tr('dismissed', [city]), action: tr('undo'), onAction: () => state.undoDismiss(city));
                    Future.delayed(const Duration(milliseconds: 300), state.refreshHome);
                  },
                ),
              ),
            ),
          ),
        ],
        SliverToBoxAdapter(child: SectionHeader(tr('vibes'), subtitle: tr('vibesSub'))),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          sliver: SliverGrid.count(
            crossAxisCount: 2,
            mainAxisSpacing: 10,
            crossAxisSpacing: 10,
            childAspectRatio: 2.6,
            children: [
              for (final v in _vibes)
                _VibeTile(
                  emoji: v.$2,
                  label: tr('vibe.${v.$1}'),
                  onTap: () => _wizard(context, WizardPrefill(suggest: true, interests: v.$3, occasion: v.$4)),
                ),
            ],
          ),
        ),
        SliverToBoxAdapter(child: SectionHeader(tr('popular'))),
        SliverToBoxAdapter(
          child: SizedBox(
            height: 190,
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              scrollDirection: Axis.horizontal,
              itemCount: _dests.length,
              separatorBuilder: (_, _) => const SizedBox(width: 12),
              itemBuilder: (_, i) {
                final (name, wiki) = _dests[i];
                return _DestCard(
                  name: name,
                  wiki: wiki,
                  onTap: () {
                    state.logActivity('view', name);
                    _wizard(context, WizardPrefill(stops: [name]));
                  },
                );
              },
            ),
          ),
        ),
        const SliverToBoxAdapter(child: SizedBox(height: 28)),
      ]),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.state});
  final AppState state;
  @override
  Widget build(BuildContext context) {
    final u = state.user;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 10, 16, 6),
      child: Row(children: [
        Container(
          width: 40, height: 40,
          decoration: BoxDecoration(gradient: const SweepGradient(colors: [DC.teal, DC.violet, DC.amber, DC.teal]),
              borderRadius: BorderRadius.circular(13)),
          padding: const EdgeInsets.all(1.6),
          child: Container(
            decoration: BoxDecoration(color: context.dark ? const Color(0xFF070B16) : Colors.white, borderRadius: BorderRadius.circular(12)),
            child: Transform.rotate(angle: .785, child: const Icon(Icons.flight_rounded, color: DC.teal, size: 22)),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(u != null ? tr('hello', [(u['name'] as String).split(' ').first]) : tr('helloGuest'),
                style: TextStyle(color: context.muted, fontSize: 13)),
            Text(tr('appName'), style: Theme.of(context).textTheme.titleLarge?.copyWith(height: 1.1)),
          ]),
        ),
        InkWell(
          borderRadius: BorderRadius.circular(999),
          onTap: () => state.goTab(3),
          child: Container(
            width: 42, height: 42,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: u != null ? const SweepGradient(colors: [DC.teal, DC.violet, DC.amber, DC.teal]) : null,
              color: u == null ? context.card2 : null,
            ),
            alignment: Alignment.center,
            child: u != null
                ? Text((u['name'] as String).trim().characters.first.toUpperCase(),
                    style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 18, color: Color(0xFF06101C)))
                : Icon(Icons.person_outline_rounded, color: context.muted),
          ),
        ),
      ]),
    );
  }
}

class _Hero extends StatefulWidget {
  const _Hero({required this.state, required this.onForm});
  final AppState state;
  final VoidCallback onForm;
  @override
  State<_Hero> createState() => _HeroState();
}

class _HeroState extends State<_Hero> {
  final _c = TextEditingController();

  void _go() {
    final text = _c.text.trim();
    if (text.isNotEmpty && widget.state.busy) {
      toast(context, tr('busyWait')); // the text stays in the box
      return;
    }
    widget.state.goTab(1);
    if (text.isNotEmpty) {
      _c.clear();
      FocusScope.of(context).unfocus();
      widget.state.send(text);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(28),
          gradient: context.dark
              ? DC.aurora
              : const LinearGradient(colors: [Color(0xFFCFF5F0), Color(0xFFDCE4FF), Color(0xFFFBE7D3)],
                  begin: Alignment.topLeft, end: Alignment.bottomRight),
        ),
        padding: const EdgeInsets.fromLTRB(20, 24, 20, 18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          ShaderMask(
            shaderCallback: (r) => (context.dark ? DC.brand : const LinearGradient(colors: [Color(0xFF0B7F74), Color(0xFF2266C4)])).createShader(r),
            child: Text(tr('whereTo'), style: Theme.of(context).textTheme.headlineLarge?.copyWith(color: Colors.white, fontSize: 34)),
          ),
          const SizedBox(height: 8),
          Text(tr('heroSub'), style: TextStyle(color: context.dark ? const Color(0xFFB9C6E0) : const Color(0xFF33425D), height: 1.4)),
          const SizedBox(height: 18),
          TextField(
            controller: _c,
            minLines: 1,
            maxLines: 4,  // a long request wraps and stays readable
            textInputAction: TextInputAction.send,
            onSubmitted: (_) => _go(),
            decoration: InputDecoration(
              hintText: tr('askPh'),
              prefixIcon: const Icon(Icons.auto_awesome_rounded, color: DC.teal),
              suffixIcon: Padding(
                padding: const EdgeInsets.all(6),
                child: IconButton.filled(
                  onPressed: _go,
                  style: IconButton.styleFrom(backgroundColor: DC.teal, foregroundColor: const Color(0xFF04110F)),
                  icon: Transform.flip(flipX: isArabic, child: const Icon(Icons.send_rounded, size: 20)),
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          IntrinsicHeight(  // both choices always the same height
            child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Expanded(child: _ChoiceTile(icon: '💬', title: tr('chatWith'), sub: tr('chatWithSub'), onTap: () => widget.state.goTab(1))),
              const SizedBox(width: 10),
              Expanded(child: _ChoiceTile(icon: '📝', title: tr('quickForm'), sub: tr('quickFormSub'), onTap: widget.onForm)),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _ChoiceTile extends StatelessWidget {
  const _ChoiceTile({required this.icon, required this.title, required this.sub, required this.onTap});
  final String icon, title, sub;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(
        color: context.dark ? Colors.white.withValues(alpha: .06) : Colors.white.withValues(alpha: .75),
        borderRadius: BorderRadius.circular(18),
        child: InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(icon, style: const TextStyle(fontSize: 24)),
              const SizedBox(height: 6),
              Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14.5)),
              Text(sub, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 12)),
            ]),
          ),
        ),
      );
}

class _ContinueCard extends StatelessWidget {
  const _ContinueCard({required this.state});
  final AppState state;
  @override
  Widget build(BuildContext context) {
    final c = state.trip!['trip_contract'] as Map<String, dynamic>? ?? {};
    final stops = (c['stops'] as List?) ?? [];
    final cities = stops.isNotEmpty ? stops.map((s) => (s['ref'] as Map)['name']).toList() : [c['destination_name'] ?? c['destination']];
    final budget = state.plan!['budget'] as Map<String, dynamic>?;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TripScreen(state: state))),
          child: Row(children: [
            SizedBox(width: 104, height: 92, child: PlacePhoto(title: '${cities.first}')),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr('continueTrip').toUpperCase(),
                    style: const TextStyle(color: DC.teal, fontWeight: FontWeight.w800, fontSize: 11, letterSpacing: .8)),
                const SizedBox(height: 2),
                Text(routeText(cities), maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleMedium),
                Text('${fmtDate(c['start_date'])} – ${fmtDate(c['end_date'])} · ${money(budget?['total'], budget?['currency'])}',
                    style: TextStyle(color: context.muted, fontSize: 12.5)),
              ]),
            ),
            Padding(padding: const EdgeInsets.all(12), child: Icon(isArabic ? Icons.chevron_left : Icons.chevron_right, color: context.muted)),
          ]),
        ),
      ),
    );
  }
}

class _VibeTile extends StatelessWidget {
  const _VibeTile({required this.emoji, required this.label, required this.onTap});
  final String emoji, label;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Card(
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(children: [
              Container(
                width: 38, height: 38, alignment: Alignment.center,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(12),
                  gradient: LinearGradient(colors: [DC.teal.withValues(alpha: .18), DC.amber.withValues(alpha: .22)]),
                ),
                child: Text(emoji, style: const TextStyle(fontSize: 19)),
              ),
              const SizedBox(width: 10),
              Expanded(child: Text(label, maxLines: 2, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5))),
            ]),
          ),
        ),
      );
}

class _DestCard extends StatelessWidget {
  const _DestCard({required this.name, required this.wiki, required this.onTap});
  final String name, wiki;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => SizedBox(
        width: 150,
        child: Card(
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onTap,
            child: Stack(fit: StackFit.expand, children: [
              PlacePhoto(title: wiki),
              const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(
                  colors: [Colors.transparent, Color(0xCC000000)], begin: Alignment.center, end: Alignment.bottomCenter))),
              Positioned(
                left: 12, right: 12, bottom: 12,
                child: Text(name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15)),
              ),
            ]),
          ),
        ),
      );
}

/// A personal suggestion from the recommendation model.
class RecCard extends StatelessWidget {
  const RecCard({super.key, required this.rec, required this.onPlan, required this.onDismiss});
  final Map<String, dynamic> rec;
  final void Function(String city) onPlan;
  final void Function(String city) onDismiss;

  String _reason() {
    final r = rec['reason'] as Map<String, dynamic>?;
    if (r == null) return '';
    final type = r['type'] as String;
    return type == 'interest' ? tr('because.interest', [tr('int.${r['interest']}')]) : tr('because.$type', [r['city']]);
  }

  @override
  Widget build(BuildContext context) {
    final tags = (rec['tags'] as List).cast<String>();
    final tint = DC.tag[tags.first] ?? DC.teal;
    final name = rec['name'] as String;
    return SizedBox(
      width: 250,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SizedBox(
            height: 136,
            child: Stack(fit: StackFit.expand, children: [
              PlacePhoto(url: rec['image'] as String?, title: rec['image'] == null ? name : null,
                  emoji: DC.emoji[tags.first] ?? '✈️', tint: tint),
              Positioned(
                top: 10, left: 10,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                  decoration: BoxDecoration(color: const Color(0xC8060C18), borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: tint.withValues(alpha: .8))),
                  child: Text(tr('match', [rec['match']]), style: const TextStyle(color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w800)),
                ),
              ),
              Positioned(
                top: 6, right: 6,
                child: IconButton(
                  tooltip: tr('notForMe'),
                  style: IconButton.styleFrom(backgroundColor: const Color(0xAA060C18), foregroundColor: Colors.white,
                      minimumSize: const Size(32, 32), padding: EdgeInsets.zero),
                  onPressed: () => onDismiss(name),
                  icon: const Icon(Icons.close_rounded, size: 18),
                ),
              ),
            ]),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(name, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleMedium),
                Text(rec['country'] as String? ?? '', style: TextStyle(color: context.muted, fontSize: 12)),
                const SizedBox(height: 8),
                Text('✨ ${_reason()}', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12.5, height: 1.3)),
                const SizedBox(height: 8),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final t in tags.take(2)) Pill('${DC.emoji[t] ?? ''} ${tr('int.$t')}', color: DC.tag[t]),
                ]),
                const SizedBox(height: 6),
                Text('${tr('knownFor')}: ${(rec['keywords'] as List).join(' · ')}',
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.faint, fontSize: 11.5)),
                const Spacer(),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    style: FilledButton.styleFrom(minimumSize: const Size(40, 42)),
                    onPressed: () => onPlan(name),
                    child: Text(tr('planThis')),
                  ),
                ),
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}
