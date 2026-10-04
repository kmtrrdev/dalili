import 'package:flutter/material.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../widgets/common.dart';
import 'trip_screen.dart';

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

  AppState get st => widget.state;

  void _send([String? text]) {
    final t = (text ?? _input.text).trim();
    if (t.isEmpty || st.busy) return;
    _input.clear();
    FocusScope.of(context).unfocus(); // close the keyboard so the progress and the answer are visible
    st.send(t);
  }

  void _toBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent + 200,
            duration: const Duration(milliseconds: 350), curve: Curves.easeOutCubic);
      }
    });
  }

  void _openTrip() => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TripScreen(state: st)));

  /// Only the agents' own next-step ideas, written for this trip and this traveller (no fixed quick replies).
  List<String> get _chips {
    if (st.busy) return [];
    return ((st.trip?['metadata'] as Map?)?['suggestions'] as List?)?.cast<String>() ?? [];
  }

  @override
  Widget build(BuildContext context) {
    if (st.messages.length != _seen || st.busy) {
      _seen = st.messages.length;
      _toBottom();
    }
    final chips = _chips;
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: Row(children: [
          Container(
            width: 38, height: 38,
            decoration: const BoxDecoration(shape: BoxShape.circle,
                gradient: RadialGradient(colors: [Color(0xFF7FF5EA), DC.teal, Color(0xFF1A6F86)], center: Alignment(-.3, -.4))),
            child: const Icon(Icons.auto_awesome_rounded, color: Color(0xFF04110F), size: 20),
          ),
          const SizedBox(width: 10),
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('chatTitle')),
            Text(st.busy ? tr('chatWorking') : tr('chatReady'),
                style: TextStyle(fontSize: 12, color: st.busy ? DC.teal : context.muted, fontWeight: FontWeight.w500)),
          ]),
        ]),
        actions: [
          if (st.plan != null)
            IconButton(tooltip: tr('viewTrip'), onPressed: _openTrip, icon: const Icon(Icons.map_rounded)),
          IconButton(tooltip: tr('newChat'), onPressed: st.busy ? null : st.newTrip, icon: const Icon(Icons.add_comment_rounded)),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.fromLTRB(14, 8, 14, 12),
            itemCount: st.messages.length + (st.busy ? 1 : 0),
            itemBuilder: (_, i) {
              if (i == st.messages.length) return _ProgressCard(progress: st.progress);
              final m = st.messages[i];
              return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                _Bubble(line: m),
                if (m.tripCard && st.plan != null && i == st.messages.length - 1) _TripReadyCard(state: st, onOpen: _openTrip),
              ]);
            },
          ),
        ),
        if (chips.isNotEmpty)
          SizedBox(
            height: 44,
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              scrollDirection: Axis.horizontal,
              itemCount: chips.length,
              separatorBuilder: (_, _) => const SizedBox(width: 8),
              itemBuilder: (_, i) => ActionChip(
                label: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 260),
                    child: Text(chips[i], overflow: TextOverflow.ellipsis)),
                onPressed: () => _send(chips[i]),
              ),
            ),
          ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _send(),
                  decoration: InputDecoration(hintText: tr('askPh')),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 52, height: 52,
                child: IconButton.filled(
                  onPressed: st.busy ? null : _send,
                  style: IconButton.styleFrom(backgroundColor: DC.teal, foregroundColor: const Color(0xFF04110F),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
                  icon: st.busy
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.2))
                      : Transform.flip(flipX: isArabic, child: const Icon(Icons.send_rounded)),
                ),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.line});
  final ChatLine line;
  @override
  Widget build(BuildContext context) {
    final me = line.role == 'user';
    return Align(
      alignment: me ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
      child: Container(
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * .84),
        margin: const EdgeInsets.symmetric(vertical: 5),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
        decoration: BoxDecoration(
          gradient: me ? DC.brand : null,
          color: me ? null : context.card,
          border: me ? null : Border.all(color: context.line),
          borderRadius: BorderRadiusDirectional.only(
            topStart: const Radius.circular(20), topEnd: const Radius.circular(20),
            bottomStart: Radius.circular(me ? 20 : 6), bottomEnd: Radius.circular(me ? 6 : 20),
          ),
        ),
        child: MdText(line.text, color: me ? const Color(0xFF04110F) : null, size: 14.5),
      ),
    );
  }
}

class _ProgressCard extends StatelessWidget {
  const _ProgressCard({required this.progress});
  final Progress? progress;
  @override
  Widget build(BuildContext context) {
    final steps = progress?.steps ?? const [];
    return Align(
      alignment: AlignmentDirectional.centerStart,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 6),
        padding: const EdgeInsets.all(14),
        width: MediaQuery.of(context).size.width * .78,
        decoration: BoxDecoration(color: context.card, borderRadius: BorderRadius.circular(20),
            border: Border.all(color: DC.teal.withValues(alpha: .35))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final s in steps)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(children: [
                SizedBox(
                  width: 20, height: 20,
                  child: s == progress!.current
                      ? const CircularProgressIndicator(strokeWidth: 2.2, color: DC.teal)
                      : const Icon(Icons.check_circle_rounded, color: DC.green, size: 20),
                ),
                const SizedBox(width: 10),
                Expanded(child: Text(tr('step.$s'), style: TextStyle(
                    fontWeight: s == progress!.current ? FontWeight.w700 : FontWeight.w500,
                    color: s == progress!.current ? null : context.muted))),
              ]),
            ),
        ]),
      ),
    );
  }
}

class _TripReadyCard extends StatelessWidget {
  const _TripReadyCard({required this.state, required this.onOpen});
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
    return Container(
      margin: const EdgeInsets.only(top: 4, bottom: 8),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onOpen,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SizedBox(
              height: 120,
              child: Stack(fit: StackFit.expand, children: [
                PlacePhoto(title: '${cities.first}'),
                const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(
                    colors: [Colors.transparent, Color(0xC0000000)], begin: Alignment.topCenter, end: Alignment.bottomCenter))),
                Positioned(
                  left: 14, right: 14, bottom: 10,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('✅ ${tr('tripReady')}', style: const TextStyle(color: DC.teal, fontWeight: FontWeight.w800, fontSize: 12)),
                    Text(routeText(cities), style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800)),
                  ]),
                ),
              ]),
            ),
            Padding(
              padding: const EdgeInsets.all(14),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${fmtDate(c['start_date'])} – ${fmtDate(c['end_date'], year: true)}', style: const TextStyle(fontWeight: FontWeight.w700)),
                    Text('${money(b?['total'], b?['currency'])} ${tr('ofBudget', [money(b?['limit'], b?['currency'])])}',
                        style: TextStyle(color: context.muted, fontSize: 12.5)),
                  ]),
                ),
                if (score != null) Pill('${tr('tripScore')} $score', color: DC.teal),
                const SizedBox(width: 8),
                FilledButton(onPressed: onOpen, style: FilledButton.styleFrom(minimumSize: const Size(40, 40)), child: Text(tr('viewTrip'))),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
