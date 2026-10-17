import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../widgets/common.dart';
import 'ideas_screen.dart';

class WizardPrefill {
  const WizardPrefill({this.suggest = false, this.stops = const [], this.interests = const [], this.occasion});
  final bool suggest;
  final List<String> stops;
  final List<String> interests;
  final String? occasion;
}

const interestKeys = ['beach', 'culture', 'history', 'nature', 'ski', 'food', 'nightlife', 'shopping', 'relax', 'adventure'];
const _occasions = ['solo', 'couple', 'honeymoon', 'family', 'friends'];
const _picks = ['Istanbul', 'Dubai', 'Paris', 'Rome', 'Sharm El Sheikh', 'Barcelona'];
const currencies = ['USD', 'EUR', 'EGP', 'SAR', 'AED', 'KWD', 'QAR', 'GBP'];

// Kept between openings in one session: the traveller shouldn't retype where they fly from or their budget.
String _lastFrom = '';
String _lastBudget = '';
String? _lastCur;

class WizardScreen extends StatefulWidget {
  const WizardScreen({super.key, required this.state, this.prefill = const WizardPrefill()});
  final AppState state;
  final WizardPrefill prefill;
  @override
  State<WizardScreen> createState() => _WizardScreenState();
}

class _WizardScreenState extends State<WizardScreen> {
  int step = 1;
  late bool suggest = widget.prefill.suggest;
  late final List<String> stops = [...widget.prefill.stops];
  late final Set<String> interests = {...widget.prefill.interests};
  late String? occasion = widget.prefill.occasion;
  final to = TextEditingController();
  late final from = TextEditingController(text: _lastFrom.isNotEmpty ? _lastFrom : (_prefs['home_city'] as String? ?? ''));
  late final budget = TextEditingController(text: _lastBudget);
  late String cur = _lastCur ?? (_prefs['currency'] as String? ?? 'USD');
  final notes = TextEditingController();
  bool flexible = false;
  DateTimeRange? range;
  int month = DateTime.now().month % 12 + 1;
  String len = 'week';
  int pax = 1;
  bool direct = false;
  bool cheapest = false; // "find the cheapest trip for me": no budget needed, the planner works out the minimum
  String? error;

  Map<String, dynamic> get _prefs => (widget.state.user?['prefs'] as Map<String, dynamic>?) ?? {};

  void _addStop([String? name]) {
    final v = (name ?? to.text).trim();
    if (v.isEmpty || stops.contains(v) || stops.length >= 6) return;
    setState(() {
      stops.add(v);
      to.clear();
      error = null;
    });
  }

  String? _check(int s) {
    if (s == 1) {
      if (!suggest && stops.isEmpty && to.text.trim().isEmpty) return tr('eWhere');
      if (from.text.trim().isEmpty) return tr('eFrom');
    }
    if (s == 2 && !flexible && range == null) return tr('eDates');
    if (s == 3 && !(cheapest && !suggest) && (parseAmount(budget.text) ?? 0) <= 0) return tr('eBudget');
    return null;
  }

  void _next() {
    if (step == 1 && to.text.trim().isNotEmpty) _addStop();
    final e = _check(step);
    setState(() => error = e);
    if (e == null && step < 4) setState(() => step++);
  }

  String get _monthName => DateFormat('MMMM', 'en').format(DateTime(2026, month));
  String get _lenText => {'weekend': 'a weekend', 'week': '1 week', 'two_weeks': '2 weeks'}[len]!;
  String get _lenAr => {'weekend': 'ويك إند', 'week': 'أسبوع', 'two_weeks': 'أسبوعين'}[len]!;
  String _iso(DateTime d) => DateFormat('yyyy-MM-dd').format(d);

  /// The same request the website's form sends, written as a chat message (the planner reads it like any message).
  String _message() {
    final n = pax, b = (parseAmount(budget.text) ?? 0).round();
    final start = range != null ? _iso(range!.start) : null, end = range != null ? _iso(range!.end) : null;
    final wishes = prefsSuffix(occasion: occasion, interests: interests, direct: direct, notes: notes.text);
    if (isArabic) {
      final where = stops.length > 1 ? 'رحلة لأكتر من مدينة بالترتيب ده: ${stops.join(' ثم ')}' : 'رحلة إلى ${stops.first}';
      final when = flexible ? '، في $_monthName لمدة $_lenAr' : '، من $start لـ $end';
      final money = cheapest ? 'وعايز أرخص رحلة ممكنة - شوفلي أقل تكلفة، والأسعار بالـ $cur' : 'وميزانيتي $b $cur';
      return 'عايز أخطط $where من ${from.text.trim()}$when، عدد المسافرين $n، $money.$wishes';
    }
    final where = stops.length > 1 ? 'a multi-city trip, visiting in this order: ${stops.join(' → ')}' : 'a trip to ${stops.first}';
    final when = flexible ? ', in $_monthName for $_lenText' : ', from $start to $end';
    final money = cheapest ? 'the cheapest trip possible - find the minimum cost for me, prices in $cur' : 'budget $b $cur';
    return 'Plan $where from ${from.text.trim()}$when, $n traveller${n > 1 ? 's' : ''}, $money.$wishes';
  }

  void _finish() {
    for (final s in [1, 2, 3]) {
      final e = _check(s);
      if (e != null) {
        setState(() {
          step = s;
          error = e;
        });
        return;
      }
    }
    _lastFrom = from.text.trim();
    _lastBudget = budget.text.trim();
    _lastCur = cur;
    final st = widget.state;
    if (suggest) {
      Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => IdeasScreen(state: st, body: {
          'budget': parseAmount(budget.text) ?? 0, 'currency': cur, 'origin': from.text.trim(), 'travelers': pax,
          'duration': len, if (flexible) 'month': month,
          if (!flexible && range != null) 'start_date': _iso(range!.start),
          if (!flexible && range != null) 'end_date': _iso(range!.end),
          'interests': interests.toList(), 'occasion': occasion, 'direct_only': direct, 'notes': notes.text.trim(),
          'lang': currentLang,
        }),
      ));
      return;
    }
    for (final s in stops) {
      st.logActivity('search', s);
    }
    final msg = _message();
    st.newTrip();
    st.goTab(1);
    Navigator.of(context).pop();
    st.send(msg);
  }

  @override
  Widget build(BuildContext context) {
    final titles = [tr('wStep1'), tr('wStep2'), tr('wStep3'), tr('wStep4')];
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(icon: const Icon(Icons.close_rounded), onPressed: () => Navigator.of(context).pop()),
        title: Text(tr('quickForm')),
      ),
      body: SafeArea(
        child: Column(children: [
          // progress: 4 labelled segments
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 10),
            child: Row(children: [
              for (var i = 1; i <= 4; i++)
                Expanded(
                  child: GestureDetector(
                    onTap: i < step ? () => setState(() => step = i) : null,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 3),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        AnimatedContainer(
                          duration: const Duration(milliseconds: 300),
                          height: 5,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(9),
                            gradient: i <= step ? DC.brand : null,
                            color: i <= step ? null : context.line,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(titles[i - 1], style: TextStyle(fontSize: 12, fontWeight: i == step ? FontWeight.w800 : FontWeight.w500,
                            color: i <= step ? null : context.faint)),
                      ]),
                    ),
                  ),
                ),
            ]),
          ),
          Expanded(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 250),
              transitionBuilder: (c, a) => FadeTransition(opacity: a,
                  child: SlideTransition(position: Tween(begin: const Offset(.06, 0), end: Offset.zero).animate(a), child: c)),
              child: ListView(
                key: ValueKey(step),
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
                children: switch (step) { 1 => _where(), 2 => _when(), 3 => _who(), _ => _loves() },
              ),
            ),
          ),
          if (error != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: DC.rose.withValues(alpha: .12), borderRadius: BorderRadius.circular(12)),
                child: Text(error!, style: const TextStyle(color: DC.rose, fontWeight: FontWeight.w700)),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
            child: Row(children: [
              if (step > 1) ...[
                OutlinedButton(onPressed: () => setState(() { step--; error = null; }), child: Text(tr('back'))),
                const SizedBox(width: 12),
              ],
              Expanded(
                child: step < 4
                    ? BrandButton(label: tr('next'), onTap: _next)
                    : BrandButton(label: suggest ? tr('showIdeas') : tr('planMyTrip'),
                        icon: suggest ? Icons.travel_explore_rounded : Icons.flight_takeoff_rounded, onTap: _finish),
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _title(String t) => Padding(padding: const EdgeInsets.only(bottom: 16, top: 6),
      child: Text(t, style: Theme.of(context).textTheme.headlineMedium));
  Widget _label(String t) => Padding(padding: const EdgeInsets.only(top: 18, bottom: 8),
      child: Text(t, style: TextStyle(fontWeight: FontWeight.w700, color: context.muted)));

  Widget _segment(List<(String, String, bool)> options, void Function(int) onTap) => Row(children: [
        for (var i = 0; i < options.length; i++) ...[
          if (i > 0) const SizedBox(width: 10),
          Expanded(
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: () => onTap(i),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(18),
                  color: options[i].$3 ? DC.teal.withValues(alpha: .14) : context.card,
                  border: Border.all(color: options[i].$3 ? DC.teal : context.line, width: options[i].$3 ? 1.6 : 1),
                ),
                child: Column(children: [
                  Text(options[i].$1, style: const TextStyle(fontSize: 24)),
                  const SizedBox(height: 4),
                  Text(options[i].$2, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800)),
                ]),
              ),
            ),
          ),
        ],
      ]);

  List<Widget> _where() => [
        _title(tr('w1T')),
        _segment([('📍', tr('wKnow'), !suggest), ('✨', tr('wSuggest'), suggest)], (i) => setState(() { suggest = i == 1; error = null; })),
        if (!suggest) ...[
          const SizedBox(height: 16),
          TextField(
            controller: to,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _addStop(),
            decoration: InputDecoration(
              hintText: tr('wToPh'),
              prefixIcon: const Icon(Icons.place_outlined),
              suffixIcon: TextButton(onPressed: _addStop, child: Text(tr('wAdd'))),
            ),
          ),
          if (stops.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              for (var i = 0; i < stops.length; i++) ...[
                if (i > 0) Text(isArabic ? '←' : '→', style: TextStyle(color: context.muted, fontWeight: FontWeight.w800)),
                InputChip(
                  label: Text(stops[i]),
                  avatar: CircleAvatar(backgroundColor: DC.teal, child: Text('${i + 1}',
                      style: const TextStyle(fontSize: 11, color: Color(0xFF04110F), fontWeight: FontWeight.w800))),
                  onDeleted: () => setState(() => stops.removeAt(i)),
                ),
              ],
            ]),
            if (stops.length == 1)
              Padding(padding: const EdgeInsets.only(top: 8), child: Text(tr('wMore'), style: TextStyle(color: context.muted, fontSize: 12.5))),
          ],
          _label(tr('wPopular')),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final p in _picks.where((p) => !stops.contains(p)))
              ActionChip(label: Text(p), onPressed: () => _addStop(p)),
          ]),
        ],
        _label(tr('wFrom')),
        TextField(controller: from, decoration: InputDecoration(hintText: tr('wFromPh'), prefixIcon: const Icon(Icons.flight_takeoff_rounded))),
      ];

  List<Widget> _when() {
    final now = DateTime.now();
    return [
      _title(tr('w2T')),
      _segment([('📅', tr('wDates'), !flexible), ('🌙', tr('wFlex'), flexible)], (i) => setState(() { flexible = i == 1; error = null; })),
      const SizedBox(height: 16),
      if (!flexible)
        Card(
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            leading: const Icon(Icons.date_range_rounded, color: DC.teal),
            title: Text(range == null ? tr('wPickDates')
                : '${fmtDate(_iso(range!.start))} – ${fmtDate(_iso(range!.end), year: true)}',
                style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: range == null ? null : Text(tr('nights', [range!.duration.inDays])),
            trailing: const Icon(Icons.edit_calendar_rounded),
            onTap: () async {
              final r = await showDateRangePicker(
                context: context,
                firstDate: now.add(const Duration(days: 1)),
                lastDate: now.add(const Duration(days: 330)),
                initialDateRange: range,
              );
              if (r != null) setState(() { range = r; error = null; });
            },
          ),
        )
      else ...[
        _label(tr('wMonth')),
        SizedBox(
          height: 44,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: 12,
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemBuilder: (_, i) {
              final m = (now.month + i) % 12 + 1;
              return ChoiceChip(
                label: Text(DateFormat('MMM', isArabic ? 'ar' : 'en').format(DateTime(2026, m))),
                selected: month == m,
                onSelected: (_) => setState(() => month = m),
              );
            },
          ),
        ),
        _label(tr('wLength')),
        Wrap(spacing: 8, children: [
          for (final l in ['weekend', 'week', 'two_weeks'])
            ChoiceChip(label: Text(tr('len.$l')), selected: len == l, onSelected: (_) => setState(() => len = l)),
        ]),
      ],
    ];
  }

  List<Widget> _who() => [
        _title(tr('w3T')),
        _label(tr('wTravellers')),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              IconButton.filledTonal(onPressed: pax > 1 ? () => setState(() => pax--) : null, icon: const Icon(Icons.remove_rounded)),
              Text('$pax', style: Theme.of(context).textTheme.headlineMedium),
              IconButton.filledTonal(onPressed: pax < 9 ? () => setState(() => pax++) : null, icon: const Icon(Icons.add_rounded)),
            ]),
          ),
        ),
        _label(tr('wTripType')),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final o in _occasions)
            ChoiceChip(label: Text(tr('occ.$o')), selected: occasion == o,
                onSelected: (v) => setState(() => occasion = v ? o : null)),
        ]),
        _label(tr('wBudget')),
        if (!suggest) // trip ideas need a budget to search within; a planned trip can find its own minimum
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(tr('wCheapest'), style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text(tr('wCheapestS'), style: TextStyle(color: context.muted)),
            value: cheapest,
            onChanged: (v) => setState(() {
              cheapest = v;
              error = null;
            }),
          ),
        Row(children: [
          Expanded(
            child: TextField(
              controller: budget,
              enabled: !(cheapest && !suggest),
              keyboardType: TextInputType.number,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
              decoration: const InputDecoration(hintText: '2000', prefixIcon: Icon(Icons.account_balance_wallet_outlined)),
            ),
          ),
          const SizedBox(width: 10),
          SizedBox(
            width: 110,
            child: DropdownButtonFormField<String>(
              initialValue: cur,
              items: [for (final c in currencies) DropdownMenuItem(value: c, child: Text(c))],
              onChanged: (v) => setState(() => cur = v ?? cur),
            ),
          ),
        ]),
      ];

  List<Widget> _loves() => [
        _title(tr('w4T')),
        Text(tr('w4S'), style: TextStyle(color: context.muted)),
        const SizedBox(height: 14),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final k in interestKeys)
            FilterChip(
              label: Text('${DC.emoji[k]} ${tr('int.$k')}'),
              selected: interests.contains(k),
              onSelected: (v) => setState(() => v ? interests.add(k) : interests.remove(k)),
            ),
        ]),
        const SizedBox(height: 10),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(tr('wDirect'), style: const TextStyle(fontWeight: FontWeight.w700)),
          value: direct,
          onChanged: (v) => setState(() => direct = v),
        ),
        _label(tr('wNotes')),
        TextField(controller: notes, maxLength: 300, decoration: InputDecoration(hintText: tr('wNotesPh'))),
      ];
}
