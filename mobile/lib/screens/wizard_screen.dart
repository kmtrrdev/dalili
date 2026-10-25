import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
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

/// A place as the pass prints it: a 3-letter code for Latin names, the first word for Arabic ones.
String passCode(String s) {
  final t = s.trim();
  if (t.isEmpty) return '---';
  if (RegExp(r'[؀-ۿ]').hasMatch(t)) {
    final w = t.split(RegExp(r'\s+')).first;
    return w.length > 8 ? w.substring(0, 8) : w;
  }
  final letters = t.toUpperCase().replaceAll(RegExp('[^A-Z]'), '');
  if (letters.isEmpty) return '---';
  return letters.length >= 3 ? letters.substring(0, 3) : letters;
}

/// The quick form as an airport check-in: four steps filling in a boarding pass at the top.
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
  bool _forward = true; // which way the step card turns
  int _errTick = 0; // each new error shakes the banner

  Map<String, dynamic> get _prefs => (widget.state.user?['prefs'] as Map<String, dynamic>?) ?? {};

  @override
  void initState() {
    super.initState();
    if (!currencies.contains(cur)) cur = 'USD';
  }

  @override
  void dispose() {
    to.dispose();
    from.dispose();
    budget.dispose();
    notes.dispose();
    super.dispose();
  }

  void _addStop([String? name]) {
    final v = (name ?? to.text).trim();
    if (v.isEmpty || stops.contains(v) || stops.length >= 6) return;
    HapticFeedback.selectionClick();
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

  void _fail(String e) {
    HapticFeedback.heavyImpact();
    setState(() {
      error = e;
      _errTick++;
    });
  }

  void _go(int s) {
    if (s == step) return;
    FocusScope.of(context).unfocus();
    HapticFeedback.selectionClick();
    setState(() {
      _forward = s > step;
      step = s;
      error = null;
    });
  }

  void _next() {
    if (step == 1 && to.text.trim().isNotEmpty) _addStop();
    final e = _check(step);
    if (e != null) return _fail(e);
    if (step < 4) _go(step + 1);
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
    if (step == 1 && to.text.trim().isNotEmpty) _addStop();
    for (final s in [1, 2, 3]) {
      final e = _check(s);
      if (e != null) {
        if (s != step) _go(s);
        _fail(e);
        return;
      }
    }
    HapticFeedback.mediumImpact();
    _lastFrom = from.text.trim();
    _lastBudget = budget.text.trim();
    _lastCur = cur;
    final st = widget.state;
    if (suggest) {
      Navigator.of(context).pushReplacement(passRoute(
        IdeasScreen(state: st, body: {
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
    st.goTab(Tabs.chat);
    Navigator.of(context).pop();
    st.send(msg);
  }

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      resizeToAvoidBottomInset: true,
      body: SkyBackground(
        planes: 2,
        child: SafeArea(
          child: Column(children: [
            _topBar(),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
              child: ListenableBuilder(
                listenable: Listenable.merge([from, to, budget]),
                builder: (context, _) => _pass(compact: keyboard),
              ),
            ),
            Expanded(child: _stepBody()),
            AnimatedSize(
              duration: const Duration(milliseconds: 220),
              curve: Curves.easeOutCubic,
              child: error == null
                  ? const SizedBox(width: double.infinity)
                  : Padding(
                      padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
                      child: TweenAnimationBuilder<double>(
                        key: ValueKey(_errTick),
                        tween: Tween(begin: 1, end: 0),
                        duration: const Duration(milliseconds: 480),
                        builder: (_, v, child) =>
                            Transform.translate(offset: Offset(math.sin(v * math.pi * 6) * 8 * v, 0), child: child),
                        child: Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: DC.rose.withValues(alpha: context.dark ? .16 : .12),
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: DC.rose.withValues(alpha: .4)),
                          ),
                          child: Text(error!, style: const TextStyle(color: DC.rose, fontWeight: FontWeight.w700)),
                        ),
                      ),
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
              child: Row(children: [
                if (step > 1) ...[
                  SizedBox(
                    height: 54,
                    child: OutlinedButton(onPressed: () => _go(step - 1), child: Text(tr('back'))),
                  ),
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
      ),
    );
  }

  Widget _topBar() => Padding(
        padding: const EdgeInsets.fromLTRB(6, 4, 16, 4),
        child: Row(children: [
          IconButton(
            tooltip: MaterialLocalizations.of(context).closeButtonTooltip,
            icon: const Icon(Icons.close_rounded),
            onPressed: () => Navigator.of(context).pop(),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(L('CHECK-IN', 'تشيك إن'), style: TextStyle(fontSize: 11, letterSpacing: 1.8, fontWeight: FontWeight.w800, color: context.faint)),
              Text(tr('quickForm'), maxLines: 1, overflow: TextOverflow.ellipsis, style: display(size: 20, color: context.ink)),
            ]),
          ),
          Directionality(
            textDirection: TextDirection.ltr,
            child: Text('0$step/04', style: mono(size: 14, color: context.muted)),
          ),
        ]),
      );

  // ---------------------------------------------------------------- the boarding pass being filled
  Widget _pass({required bool compact}) {
    final titles = [tr('wStep1'), tr('wStep2'), tr('wStep3'), tr('wStep4')];
    final fromCode = passCode(from.text);
    final pending = to.text.trim();
    final toCode = suggest ? '✨' : passCode(stops.isNotEmpty ? stops.first : pending);
    final extra = suggest ? 0 : stops.length - 1;
    final b = parseAmount(budget.text);
    final dates = flexible
        ? '${DateFormat('MMM', isArabic ? 'ar' : 'en').format(DateTime(2026, month))} · ${tr('len.$len')}'
        : range == null
            ? '—'
            : '${fmtDate(_iso(range!.start))} – ${fmtDate(_iso(range!.end))}';
    final budgetText = cheapest && !suggest ? L('Lowest', 'الأرخص') : (b != null && b > 0 ? money(b, cur) : '—');

    Widget code(String c, String label, String city, {bool end = false}) => Column(
          crossAxisAlignment: end ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label.toUpperCase(), style: TextStyle(fontSize: 10, letterSpacing: 1.2, fontWeight: FontWeight.w800, color: context.faint)),
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 260),
              transitionBuilder: (c, a) => ScaleTransition(scale: a, child: FadeTransition(opacity: a, child: c)),
              child: Text(c, key: ValueKey(c), style: mono(size: compact ? 20 : 26, weight: FontWeight.w800, color: context.ink)),
            ),
            if (!compact)
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 96),
                child: Text(city, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: context.muted)),
              ),
          ],
        );

    final route = Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
      code(fromCode, L('From', 'من'), from.text.trim().isEmpty ? '—' : from.text.trim()),
      Expanded(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: step / 4),
            duration: const Duration(milliseconds: 750),
            curve: Curves.easeInOutCubic,
            builder: (_, v, _) => RouteArc(progress: v, height: compact ? 28 : 42, color: context.dark ? DC.teal : DC.tealDeep),
          ),
        ),
      ),
      Stack(clipBehavior: Clip.none, children: [
        code(toCode, L('To', 'إلى'), suggest ? tr('wSuggest') : (stops.isNotEmpty ? stops.join(' · ') : (pending.isEmpty ? '—' : pending)), end: true),
        if (extra > 0)
          PositionedDirectional(end: -6, top: -4, child: Pill('+$extra', color: DC.amber, solid: true)),
      ]),
    ]);

    return Ticket(
      elevation: 8,
      notch: 11,
      gap: 18,
      main: Padding(
        padding: EdgeInsets.fromLTRB(16, compact ? 10 : 14, 16, compact ? 8 : 12),
        child: AnimatedSize(
          duration: const Duration(milliseconds: 240),
          curve: Curves.easeOutCubic,
          alignment: Alignment.topCenter,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            route,
            if (!compact) ...[
              const SizedBox(height: 10),
              Row(children: [
                Expanded(flex: 5, child: PassField(L('Dates', 'التواريخ'), dates)),
                const SizedBox(width: 8),
                Expanded(flex: 2, child: PassField(L('Pax', 'أفراد'), '$pax')),
                const SizedBox(width: 8),
                Expanded(flex: 4, child: PassField(tr('wStep3'), budgetText, end: true)),
              ]),
            ],
          ]),
        ),
      ),
      stub: Padding(
        padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
        child: Row(children: [
          for (var i = 1; i <= 4; i++)
            Expanded(
              child: Pressable(
                onTap: i < step ? () => _go(i) : null,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 260),
                  constraints: const BoxConstraints(minHeight: 46),
                  margin: const EdgeInsets.symmetric(horizontal: 3),
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    color: i == step ? DC.amber.withValues(alpha: context.dark ? .18 : .22) : Colors.transparent,
                  ),
                  child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Text(i < step ? '✓' : '0$i',
                        style: mono(size: 12, color: i < step ? (context.dark ? DC.teal : DC.tealDeep) : (i == step ? DC.amber : context.faint))),
                    Text(titles[i - 1], maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 11.5, fontWeight: i == step ? FontWeight.w800 : FontWeight.w600,
                            color: i <= step ? context.ink : context.faint)),
                  ]),
                ),
              ),
            ),
        ]),
      ),
    );
  }

  // ---------------------------------------------------------------- the step card, turning in 3D
  Widget _stepBody() {
    final rtl = Directionality.of(context) == TextDirection.rtl;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 460),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeInCubic,
      layoutBuilder: (current, previous) => Stack(fit: StackFit.expand, children: [...previous, ?current]),
      transitionBuilder: (child, anim) {
        final incoming = child.key == ValueKey(step);
        // Forward: the new card comes in from the reading end, the old one leaves toward the start.
        final side = (incoming ? 1.0 : -1.0) * (_forward ? 1 : -1) * (rtl ? -1 : 1);
        return AnimatedBuilder(
          animation: anim,
          child: child,
          builder: (context, child) {
            final t = 1 - anim.value;
            return Opacity(
              opacity: anim.value.clamp(0.0, 1.0),
              child: Transform(
                alignment: Alignment.center,
                transform: perspective()
                  ..translateByDouble(side * t * 70, 0, 0, 1)
                  ..rotateY(-side * t * .9)
                  ..scaleByDouble(1 - t * .08, 1 - t * .08, 1, 1),
                child: child,
              ),
            );
          },
        );
      },
      child: ListView(
        key: ValueKey(step),
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        children: switch (step) { 1 => _where(), 2 => _when(), 3 => _who(), _ => _loves() },
      ),
    );
  }

  Widget _title(String t) => Padding(padding: const EdgeInsets.only(bottom: 16, top: 6),
      child: Text(t, style: display(size: 24, color: context.ink, height: 1.2)));
  Widget _label(String t) => Padding(padding: const EdgeInsets.only(top: 20, bottom: 8),
      child: Text(t.toUpperCase(), style: TextStyle(fontSize: 11.5, letterSpacing: 1.1, fontWeight: FontWeight.w800, color: context.muted)));

  /// Two big choices drawn as small tickets; the chosen one lights up.
  Widget _segment(List<(String, String, bool)> options, void Function(int) onTap) => Row(children: [
        for (var i = 0; i < options.length; i++) ...[
          if (i > 0) const SizedBox(width: 10),
          Expanded(
            child: Pressable(
              onTap: () => onTap(i),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 240),
                curve: Curves.easeOut,
                padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 10),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(18),
                  color: options[i].$3 ? null : context.ticket,
                  gradient: options[i].$3
                      ? LinearGradient(colors: [DC.teal.withValues(alpha: .28), DC.sky.withValues(alpha: .18)],
                          begin: Alignment.topLeft, end: Alignment.bottomRight)
                      : null,
                  border: Border.all(color: options[i].$3 ? DC.teal : context.ticketEdge, width: options[i].$3 ? 1.6 : 1),
                  boxShadow: [
                    if (options[i].$3) BoxShadow(color: DC.teal.withValues(alpha: .25), blurRadius: 18, offset: const Offset(0, 6)),
                  ],
                ),
                child: Column(children: [
                  AnimatedScale(
                    scale: options[i].$3 ? 1.15 : 1,
                    duration: const Duration(milliseconds: 240),
                    child: Text(options[i].$1, style: const TextStyle(fontSize: 26)),
                  ),
                  const SizedBox(height: 6),
                  Text(options[i].$2, textAlign: TextAlign.center, style: TextStyle(fontWeight: FontWeight.w800, color: context.ink)),
                ]),
              ),
            ),
          ),
        ],
      ]);

  List<Widget> _where() => [
        _title(tr('w1T')),
        _segment([('📍', tr('wKnow'), !suggest), ('✨', tr('wSuggest'), suggest)], (i) => setState(() {
              suggest = i == 1;
              error = null;
            })),
        if (!suggest) ...[
          const SizedBox(height: 16),
          TextField(
            controller: to,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _addStop(),
            decoration: InputDecoration(
              hintText: tr('wToPh'),
              prefixIcon: const Icon(Icons.place_outlined),
              suffixIcon: Padding(
                padding: const EdgeInsetsDirectional.only(end: 4),
                child: TextButton(onPressed: _addStop, child: Text(tr('wAdd'))),
              ),
            ),
          ),
          if (stops.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              for (var i = 0; i < stops.length; i++) ...[
                if (i > 0) Text(isArabic ? '←' : '→', style: TextStyle(color: context.muted, fontWeight: FontWeight.w800)),
                Reveal(
                  key: ValueKey(stops[i]),
                  offset: 10,
                  duration: const Duration(milliseconds: 320),
                  child: InputChip(
                    label: Text(stops[i]),
                    avatar: CircleAvatar(backgroundColor: DC.teal, child: Text('${i + 1}',
                        style: const TextStyle(fontSize: 11, color: DC.onBrand, fontWeight: FontWeight.w800))),
                    onDeleted: () => setState(() => stops.removeAt(i)),
                  ),
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
        TextField(
          controller: from,
          textInputAction: TextInputAction.done,
          decoration: InputDecoration(hintText: tr('wFromPh'), prefixIcon: const Icon(Icons.flight_takeoff_rounded)),
        ),
      ];

  List<Widget> _when() {
    final now = DateTime.now();
    return [
      _title(tr('w2T')),
      _segment([('📅', tr('wDates'), !flexible), ('🌙', tr('wFlex'), flexible)], (i) => setState(() {
            flexible = i == 1;
            error = null;
          })),
      const SizedBox(height: 16),
      if (!flexible)
        Pressable(
          onTap: () async {
            final r = await showDateRangePicker(
              context: context,
              firstDate: now.add(const Duration(days: 1)),
              lastDate: now.add(const Duration(days: 330)),
              initialDateRange: range,
            );
            if (r != null) {
              HapticFeedback.selectionClick();
              setState(() {
                range = r;
                error = null;
              });
            }
          },
          child: Ticket(
            axis: Axis.horizontal,
            elevation: 5,
            notch: 10,
            gap: 16,
            main: Padding(
              padding: const EdgeInsets.all(16),
              child: range == null
                  ? Row(children: [
                      Icon(Icons.date_range_rounded, color: context.dark ? DC.teal : DC.tealDeep),
                      const SizedBox(width: 10),
                      Expanded(child: Text(tr('wPickDates'), style: TextStyle(fontWeight: FontWeight.w700, color: context.ink))),
                    ])
                  : Row(children: [
                      Expanded(child: PassField(tr('outbound'), fmtDate(_iso(range!.start), year: true))),
                      const SizedBox(width: 8),
                      Expanded(child: PassField(tr('return'), fmtDate(_iso(range!.end), year: true))),
                    ]),
            ),
            stub: SizedBox(
              width: 64,
              child: Center(
                child: range == null
                    ? Icon(Icons.edit_calendar_rounded, color: context.muted)
                    : Column(mainAxisSize: MainAxisSize.min, children: [
                        Text('${range!.duration.inDays}', style: mono(size: 22, color: DC.amber)),
                        Text(L('nights', 'ليالي'), style: TextStyle(fontSize: 11, color: context.muted)),
                      ]),
              ),
            ),
          ),
        )
      else ...[
        _label(tr('wMonth')),
        SizedBox(
          height: 48,
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
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final l in ['weekend', 'week', 'two_weeks'])
            ChoiceChip(label: Text(tr('len.$l')), selected: len == l, onSelected: (_) => setState(() => len = l)),
        ]),
      ],
    ];
  }

  List<Widget> _who() => [
        _title(tr('w3T')),
        _label(tr('wTravellers')),
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: context.ticket,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: context.ticketEdge),
          ),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            IconButton.filledTonal(
              onPressed: pax > 1 ? () => setState(() => pax--) : null,
              icon: const Icon(Icons.remove_rounded),
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            ),
            Row(mainAxisSize: MainAxisSize.min, children: [
              Text('🧳' * math.min(pax, 3), style: const TextStyle(fontSize: 16)),
              const SizedBox(width: 8),
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 220),
                transitionBuilder: (c, a) => ScaleTransition(scale: a, child: c),
                child: Text('$pax', key: ValueKey(pax), style: mono(size: 32, color: context.ink)),
              ),
            ]),
            IconButton.filledTonal(
              onPressed: pax < 9 ? () => setState(() => pax++) : null,
              icon: const Icon(Icons.add_rounded),
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
            ),
          ]),
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
        AnimatedOpacity(
          duration: const Duration(milliseconds: 200),
          opacity: cheapest && !suggest ? .45 : 1,
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: budget,
                enabled: !(cheapest && !suggest),
                keyboardType: TextInputType.number,
                textDirection: TextDirection.ltr,
                style: mono(size: 20, weight: FontWeight.w800, color: context.ink),
                decoration: const InputDecoration(hintText: '2000', prefixIcon: Icon(Icons.account_balance_wallet_outlined)),
              ),
            ),
            const SizedBox(width: 10),
            SizedBox(
              width: 112,
              child: DropdownButtonFormField<String>(
                initialValue: cur,
                style: mono(size: 14, color: context.ink),
                items: [for (final c in currencies) DropdownMenuItem(value: c, child: Text(c))],
                onChanged: (v) => setState(() => cur = v ?? cur),
              ),
            ),
          ]),
        ),
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
              selectedColor: (DC.tag[k] ?? DC.teal).withValues(alpha: .25),
              onSelected: (v) {
                HapticFeedback.selectionClick();
                setState(() => v ? interests.add(k) : interests.remove(k));
              },
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
