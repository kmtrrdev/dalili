import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';

// ---------------------------------------------------------------- event helpers (pure: tested in events_helpers_test)
const eventCategories = ['sports', 'festival', 'music', 'culture'];
const _catEmoji = {'sports': '⚽', 'festival': '🎉', 'music': '🎬', 'culture': '🏮'};
const _catColor = {'sports': DC.green, 'festival': DC.rose, 'music': DC.violet, 'culture': DC.amber};

Color eventColor(String? category) => _catColor[category] ?? DC.teal;
String eventEmoji(String? category) => _catEmoji[category] ?? '✨';

String categoryLabel(String c) => switch (c) {
      'sports' => L('Sports', 'رياضة'),
      'festival' => L('Festivals', 'مهرجانات'),
      'music' => L('Music, film & arts', 'موسيقى وسينما وفنون'),
      'culture' => L('Culture & seasons', 'ثقافة ومواسم'),
      _ => c,
    };

// The server sends ISO country codes only; Dart has no region-name API, so the usual hosts are named here
// (any other code is shown as it is, next to its flag).
const _countries = {
  'AE': ('United Arab Emirates', 'الإمارات'), 'AR': ('Argentina', 'الأرجنتين'), 'AT': ('Austria', 'النمسا'),
  'AU': ('Australia', 'أستراليا'), 'AZ': ('Azerbaijan', 'أذربيجان'), 'BE': ('Belgium', 'بلجيكا'), 'BH': ('Bahrain', 'البحرين'),
  'BR': ('Brazil', 'البرازيل'), 'CA': ('Canada', 'كندا'), 'CH': ('Switzerland', 'سويسرا'), 'CL': ('Chile', 'تشيلي'),
  'CN': ('China', 'الصين'), 'CO': ('Colombia', 'كولومبيا'), 'CZ': ('Czechia', 'التشيك'), 'DE': ('Germany', 'ألمانيا'),
  'DK': ('Denmark', 'الدنمارك'), 'EG': ('Egypt', 'مصر'), 'ES': ('Spain', 'إسبانيا'), 'FI': ('Finland', 'فنلندا'),
  'FR': ('France', 'فرنسا'), 'GB': ('United Kingdom', 'بريطانيا'), 'GR': ('Greece', 'اليونان'), 'HK': ('Hong Kong', 'هونج كونج'),
  'HU': ('Hungary', 'المجر'), 'ID': ('Indonesia', 'إندونيسيا'), 'IE': ('Ireland', 'أيرلندا'), 'IN': ('India', 'الهند'),
  'IT': ('Italy', 'إيطاليا'), 'JO': ('Jordan', 'الأردن'), 'JP': ('Japan', 'اليابان'), 'KR': ('South Korea', 'كوريا الجنوبية'),
  'KW': ('Kuwait', 'الكويت'), 'LB': ('Lebanon', 'لبنان'), 'MA': ('Morocco', 'المغرب'), 'MC': ('Monaco', 'موناكو'),
  'MX': ('Mexico', 'المكسيك'), 'MY': ('Malaysia', 'ماليزيا'), 'NL': ('Netherlands', 'هولندا'), 'NO': ('Norway', 'النرويج'),
  'NZ': ('New Zealand', 'نيوزيلندا'), 'OM': ('Oman', 'عُمان'), 'PE': ('Peru', 'بيرو'), 'PH': ('Philippines', 'الفلبين'),
  'PL': ('Poland', 'بولندا'), 'PT': ('Portugal', 'البرتغال'), 'QA': ('Qatar', 'قطر'), 'RU': ('Russia', 'روسيا'),
  'SA': ('Saudi Arabia', 'السعودية'), 'SE': ('Sweden', 'السويد'), 'SG': ('Singapore', 'سنغافورة'), 'TH': ('Thailand', 'تايلاند'),
  'TN': ('Tunisia', 'تونس'), 'TR': ('Türkiye', 'تركيا'), 'TW': ('Taiwan', 'تايوان'), 'US': ('United States', 'أمريكا'),
  'VN': ('Vietnam', 'فيتنام'), 'ZA': ('South Africa', 'جنوب أفريقيا'),
};

String countryName(String? cc) {
  final c = (cc ?? '').toUpperCase();
  final n = _countries[c];
  return n == null ? c : (isArabic ? n.$2 : n.$1);
}

/// The country's flag emoji (two regional-indicator letters); '' for anything that isn't a two-letter code.
String flagOf(String? cc) {
  final c = (cc ?? '').toUpperCase();
  if (!RegExp(r'^[A-Z]{2}$').hasMatch(c)) return '';
  return String.fromCharCodes(c.codeUnits.map((u) => 0x1F1E6 + u - 0x41));
}

DateTime? eventDay(dynamic iso) => iso is String && iso.length >= 10 ? DateTime.tryParse(iso.substring(0, 10)) : null;

String _s(dynamic v) => v is String ? v : '';

String eventName(Map e) => isArabic && _s(e['name_ar']).isNotEmpty ? _s(e['name_ar']) : _s(e['name']);

String eventPlace(Map e) {
  final city = isArabic && _s(e['city_ar']).isNotEmpty ? _s(e['city_ar']) : _s(e['city']);
  return [city, countryName(_s(e['country_code']))].where((x) => x.isNotEmpty).join(isArabic ? '، ' : ', ');
}

/// False when the dates are only the event's usual ones (the web's "usual dates · confirm").
bool datesConfirmed(Map e) => e['dates_confirmed'] is bool ? e['dates_confirmed'] as bool : e['dates_source'] != 'usual dates';

/// "12 Jul 2026" or "3 Dec – 7 Dec 2026", in the app's language.
String eventSpan(Map e) {
  final a = eventDay(e['start']), b = eventDay(e['end']) ?? a;
  if (a == null) return '';
  final loc = isArabic ? 'ar' : 'en';
  final full = DateFormat('d MMM y', loc);
  if (b == null || b == a) return full.format(a);
  return '${DateFormat('d MMM', loc).format(a)} – ${full.format(b)}';
}

bool eventOnNow(Map e, [DateTime? today]) {
  final a = eventDay(e['start']), b = eventDay(e['end']) ?? a;
  if (a == null || b == null) return false;
  final t = today ?? DateTime.now();
  final d = DateTime(t.year, t.month, t.day);
  return !d.isBefore(a) && !d.isAfter(b);
}

/// The events by the month they start in ("2026-12"), months in order, each sorted by date then fame.
List<(String, List<Map<String, dynamic>>)> groupByMonth(List<Map<String, dynamic>> events) {
  final sorted = [...events]..sort((x, y) {
      final c = _s(x['start']).compareTo(_s(y['start']));
      return c != 0 ? c : ((y['fame'] as num?) ?? 0).compareTo((x['fame'] as num?) ?? 0);
    });
  final out = <(String, List<Map<String, dynamic>>)>[];
  for (final e in sorted) {
    final start = _s(e['start']);
    final k = start.length >= 7 ? start.substring(0, 7) : '';
    if (out.isEmpty || out.last.$1 != k) out.add((k, []));
    out.last.$2.add(e);
  }
  return out;
}

/// "Plan a trip to Monaco, Monaco to attend Monaco Grand Prix (5 Jun – 7 Jun 2026)" - the same words as the website.
String eventPlanMessage(Map e) {
  final name = eventName(e), place = eventPlace(e), dates = eventSpan(e);
  return isArabic ? 'عايز أسافر $place عشان أحضر $name ($dates)' : 'Plan a trip to $place to attend $name ($dates)';
}

/// "From €120 · official site", "Free or see the site", or null when the event says nothing about tickets.
String? ticketText(Map e) {
  final t = e['ticket'];
  if (t is! Map) return e.containsKey('ticket') ? L('Free or see the site', 'ببلاش أو شوف الموقع') : null;
  final amount = t['amount'] as num?;
  if (amount == null) return null;
  final src = t['source'] == 'official site' ? L('official site', 'الموقع الرسمي') : L('AI estimate', 'تقدير AI');
  return '${L('From', 'من')} ${money(amount, t['currency'] as String?)} · $src';
}

/// The month code on a stub ("DEC") and the board ("DEC 03"): Latin in both languages, like a real ticket.
String _mmm(DateTime d) => DateFormat('MMM', 'en').format(d).toUpperCase();
String _dd(DateTime d) => d.day.toString().padLeft(2, '0');

String? _wikiTitle(String url) {
  final i = url.indexOf('/wiki/');
  if (i < 0) return null;
  try {
    return Uri.decodeComponent(url.substring(i + 6)).replaceAll('_', ' ');
  } catch (_) {
    return null;
  }
}

// ---------------------------------------------------------------- the tab
/// World-famous events in the coming months, as a stack of concert tickets under a departures board.
class EventsScreen extends StatefulWidget {
  const EventsScreen({super.key, required this.state});
  final AppState state;

  @override
  State<EventsScreen> createState() => _EventsScreenState();
}

class _EventsScreenState extends State<EventsScreen> {
  static const _pollEvery = Duration(seconds: 6); // like the web: the catalogue is built in the background
  List<Map<String, dynamic>>? _events;
  bool _complete = false;
  bool _failed = false;
  String _cat = 'all';
  String _country = '';
  int _polls = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool reset = false}) async {
    _timer?.cancel();
    if (reset) _polls = 0;
    try {
      final r = await widget.state.api.get('/api/events') as Map<String, dynamic>;
      final list = (r['events'] as List? ?? []).whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList();
      if (!mounted) return;
      setState(() {
        _events = list;
        _complete = r['complete'] == true;
        _failed = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _failed = _events == null); // offline: keep what we already show
    }
    if (_events != null && !_complete && _polls++ < 40) _timer = Timer(_pollEvery, _load);
  }

  void _retry() {
    setState(() => _failed = false);
    _load(reset: true);
  }

  void _open(Map<String, dynamic> e) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: false,
      backgroundColor: Colors.transparent,
      builder: (_) => EventDetailSheet(event: e, onPlan: () => _plan(e)),
    );
  }

  void _plan(Map<String, dynamic> e) {
    final s = widget.state;
    Navigator.of(context).pop(); // the sheet
    if (s.busy) {
      toast(context, tr('busyWait'));
      return;
    }
    unawaited(s.send(eventPlanMessage(e)));
    s.goTab(Tabs.chat);
  }

  Future<void> _pickCountry() async {
    final codes = {for (final e in _events ?? const <Map<String, dynamic>>[]) _s(e['country_code'])}.where((c) => c.isNotEmpty).toList()
      ..sort((a, b) => countryName(a).compareTo(countryName(b)));
    final picked = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .6,
        maxChildSize: .92,
        builder: (ctx, sc) => ListView(
          controller: sc,
          padding: EdgeInsets.only(bottom: 16 + MediaQuery.viewPaddingOf(ctx).bottom),
          children: [
            _CountryRow(flag: '🌍', name: L('Every country', 'كل الدول'), selected: _country.isEmpty, onTap: () => Navigator.pop(ctx, '')),
            for (final c in codes)
              _CountryRow(flag: flagOf(c), name: countryName(c), selected: _country == c, onTap: () => Navigator.pop(ctx, c)),
          ],
        ),
      ),
    );
    if (picked != null && mounted) setState(() => _country = picked);
  }

  @override
  Widget build(BuildContext context) {
    final all = _events;
    final visible = all
        ?.where((e) => (_cat == 'all' || e['category'] == _cat) && (_country.isEmpty || e['country_code'] == _country))
        .toList();
    final groups = visible == null ? null : groupByMonth(visible);
    final top = MediaQuery.paddingOf(context).top;
    // The board shows the next event still to come (or the first one, when they have all started).
    Map<String, dynamic>? next;
    if (groups != null && groups.isNotEmpty) {
      final today = DateTime.now();
      final flat = [for (final g in groups) ...g.$2];
      next = flat.firstWhere((e) => !(eventDay(e['start'])?.isBefore(DateTime(today.year, today.month, today.day)) ?? true),
          orElse: () => flat.first);
    }
    final nextDay = next == null ? null : eventDay(next['start']);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: RefreshIndicator(
        edgeOffset: top,
        onRefresh: () => _load(reset: true),
        child: CustomScrollView(
          physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.only(top: top + 12),
                child: _Board(next: nextDay == null ? null : '${_mmm(nextDay)} ${_dd(nextDay)}', count: visible?.length),
              ),
            ),
            SliverToBoxAdapter(
              child: _Filters(
                cat: _cat,
                country: _country,
                onCat: (c) => setState(() => _cat = c),
                onCountry: all == null || all.isEmpty ? null : _pickCountry,
              ),
            ),
            if (all != null && !_complete) const SliverToBoxAdapter(child: _StillChecking()),
            if (all == null && _failed)
              SliverToBoxAdapter(child: _ErrorBox(onRetry: _retry))
            else if (all == null)
              const _SkeletonSliver()
            else if (visible!.isEmpty)
              SliverToBoxAdapter(
                child: _complete
                    ? EmptyState(emoji: '🎟️', title: L('No events here for now.', 'مفيش إيفنتات هنا دلوقتي.'))
                    : const SizedBox(height: 40),
              )
            else
              for (final (month, list) in groups!)
                SliverMainAxisGroup(slivers: [
                  SliverPersistentHeader(
                    pinned: true,
                    delegate: _MonthHeader(month, MediaQuery.textScalerOf(context).scale(16) + 30, context.dark),
                  ),
                  SliverPadding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    sliver: SliverList.builder(
                      itemCount: list.length,
                      itemBuilder: (_, i) => Padding(
                        padding: const EdgeInsets.only(bottom: 14),
                        child: Reveal(
                          key: ValueKey('$_cat|$_country|${list[i]['id']}'),
                          delay: Duration(milliseconds: 55 * i.clamp(0, 5)),
                          child: EventTicket(event: list[i], onTap: () => _open(list[i])),
                        ),
                      ),
                    ),
                  ),
                ]),
            SliverToBoxAdapter(child: SizedBox(height: context.dockSpace + 8)),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- the departures board
class _Board extends StatelessWidget {
  const _Board({required this.next, required this.count});
  final String? next;
  final int? count;

  static const _boardBg = Color(0xFF0A0F1C);
  static const _tile = Color(0xFF172036);

  @override
  Widget build(BuildContext context) {
    // Board letters are Latin and always read left to right, also in Arabic.
    Widget flap(String text, TextStyle style, {Duration delay = Duration.zero}) => Directionality(
          textDirection: TextDirection.ltr,
          child: RepaintBoundary(child: SplitFlap(text, style: style, tileColor: _tile, delay: delay)),
        );
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16),
      padding: const EdgeInsetsDirectional.fromSTEB(18, 16, 18, 18),
      decoration: BoxDecoration(
        color: _boardBg,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: Colors.white.withValues(alpha: .08)),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .5 : .22), blurRadius: 24, offset: const Offset(0, 10))],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 8, height: 8, decoration: const BoxDecoration(color: DC.amber, shape: BoxShape.circle)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(L('DEPARTURES · WORLD EVENTS', 'لوحة المواعيد · إيفنتات العالم'),
                maxLines: 1, overflow: TextOverflow.ellipsis,
                style: isArabic
                    ? display(size: 12, weight: FontWeight.w700, color: DC.amber)
                    : mono(size: 11, color: DC.amber, spacing: 1.6)),
          ),
          if (count != null) Text('$count', style: mono(size: 13, color: Colors.white70)),
        ]),
        const SizedBox(height: 14),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: AlignmentDirectional.centerStart,
          child: flap('EVENTS', mono(size: 30, weight: FontWeight.w800, color: Colors.white)),
        ),
        const SizedBox(height: 12),
        Text(L('Big events around the world', 'أكبر الإيفنتات حوالين العالم'),
            style: display(size: 20, color: Colors.white, height: 1.2)),
        const SizedBox(height: 4),
        Text(
          L('Championships, Grands Prix, festivals and celebrations - each checked with Wikipedia. Pick one and Dalili plans the trip around it.',
              'بطولات وسباقات ومهرجانات واحتفالات - كل واحدة متأكدين منها من ويكيبيديا. اختار واحدة ودليلي يخطط الرحلة حواليها.'),
          style: TextStyle(color: Colors.white.withValues(alpha: .7), fontSize: 13, height: 1.4),
        ),
        if (next != null) ...[
          const SizedBox(height: 14),
          Row(children: [
            Text(L('NEXT', 'الجاي'),
                style: isArabic ? display(size: 13, color: DC.amber) : mono(size: 11, color: DC.amber, spacing: 1.6)),
            const SizedBox(width: 10),
            Flexible(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: AlignmentDirectional.centerStart,
                child: flap(next!, mono(size: 17, color: DC.amber), delay: const Duration(milliseconds: 250)),
              ),
            ),
          ]),
        ],
      ]),
    );
  }
}

// ---------------------------------------------------------------- filters
class _Filters extends StatelessWidget {
  const _Filters({required this.cat, required this.country, required this.onCat, required this.onCountry});
  final String cat;
  final String country;
  final ValueChanged<String> onCat;
  final VoidCallback? onCountry;

  @override
  Widget build(BuildContext context) {
    final chips = <Widget>[
      _Chip(emoji: '🎟️', label: L('All', 'الكل'), color: DC.teal, selected: cat == 'all', onTap: () => onCat('all')),
      for (final c in eventCategories)
        _Chip(emoji: eventEmoji(c), label: categoryLabel(c), color: eventColor(c), selected: cat == c, onTap: () => onCat(c)),
      _Chip(
        emoji: country.isEmpty ? '🌍' : flagOf(country),
        label: '${country.isEmpty ? L('Every country', 'كل الدول') : countryName(country)}  ▾',
        color: DC.sky,
        selected: country.isNotEmpty,
        onTap: onCountry,
      ),
    ];
    return SizedBox(
      height: MediaQuery.textScalerOf(context).scale(14) + 46,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
        scrollDirection: Axis.horizontal,
        itemCount: chips.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, i) => chips[i],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.emoji, required this.label, required this.color, required this.selected, required this.onTap});
  final String emoji;
  final String label;
  final Color color;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        selected: selected,
        child: Pressable(
          onTap: onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 280),
            curve: Curves.easeOutCubic,
            constraints: const BoxConstraints(minHeight: 44),
            padding: const EdgeInsets.symmetric(horizontal: 14),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: selected ? color : context.card.withValues(alpha: .92),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: selected ? color : context.line),
              boxShadow: selected ? [BoxShadow(color: color.withValues(alpha: .38), blurRadius: 16, offset: const Offset(0, 5))] : const [],
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              AnimatedScale(
                scale: selected ? 1.18 : 1,
                duration: const Duration(milliseconds: 280),
                curve: Curves.easeOutBack,
                child: Text(emoji, style: const TextStyle(fontSize: 15)),
              ),
              const SizedBox(width: 7),
              AnimatedDefaultTextStyle(
                duration: const Duration(milliseconds: 220),
                style: DefaultTextStyle.of(context).style.copyWith(
                    fontSize: 13.5, fontWeight: FontWeight.w700, color: selected ? DC.onBrand : context.ink),
                child: Text(label, maxLines: 1),
              ),
            ]),
          ),
        ),
      );
}

class _CountryRow extends StatelessWidget {
  const _CountryRow({required this.flag, required this.name, required this.selected, required this.onTap});
  final String flag;
  final String name;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => ListTile(
        minTileHeight: 52,
        leading: Text(flag, style: const TextStyle(fontSize: 22)),
        title: Text(name, style: TextStyle(fontWeight: selected ? FontWeight.w800 : FontWeight.w600)),
        trailing: selected ? const Icon(Icons.check_circle_rounded, color: DC.teal) : null,
        onTap: onTap,
      );
}

class _StillChecking extends StatelessWidget {
  const _StillChecking();

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 10, 20, 2),
        child: Row(children: [
          const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: DC.teal)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(L('More events are still being checked - they appear here in a moment.',
                    'لسه في إيفنتات بتتراجع - هتظهر هنا كمان شوية.'),
                style: TextStyle(color: context.muted, fontSize: 12.5)),
          ),
        ]),
      );
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.onRetry});
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 40),
        child: Column(children: [
          const Float(child: Text('📡', style: TextStyle(fontSize: 52))),
          const SizedBox(height: 12),
          Text(L("Couldn't load the events", 'معرفتش أجيب الإيفنتات'),
              textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 6),
          Text(tr('errNet'), textAlign: TextAlign.center, style: TextStyle(color: context.muted)),
          const SizedBox(height: 18),
          OutlinedButton(onPressed: onRetry, child: Text('↻  ${L('Try again', 'جرّب تاني')}')),
        ]),
      );
}

// ---------------------------------------------------------------- sticky month header
class _MonthHeader extends SliverPersistentHeaderDelegate {
  _MonthHeader(this.month, this.extent, this.dark);
  final String month; // "2026-12"
  final double extent;
  final bool dark;

  @override
  double get minExtent => extent;
  @override
  double get maxExtent => extent;

  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlapsContent) {
    final d = DateTime.tryParse('$month-01');
    final label = d == null ? month : DateFormat('MMMM y', isArabic ? 'ar' : 'en').format(d);
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(16, 6, 16, 6),
      child: Align(
        alignment: AlignmentDirectional.centerStart,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsetsDirectional.fromSTEB(6, 4, 14, 4),
          decoration: BoxDecoration(
            color: context.card.withValues(alpha: overlapsContent || shrinkOffset > 0 ? .97 : .85),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: context.line),
            boxShadow: overlapsContent || shrinkOffset > 0
                ? [BoxShadow(color: Colors.black.withValues(alpha: dark ? .4 : .12), blurRadius: 12, offset: const Offset(0, 4))]
                : const [],
          ),
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (d != null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(color: const Color(0xFF0A0F1C), borderRadius: BorderRadius.circular(999)),
                  child: Text(_mmm(d), style: mono(size: 11, color: DC.amber, spacing: 1.4)),
                ),
              const SizedBox(width: 8),
              Text(label, style: display(size: 15, weight: FontWeight.w700, color: context.ink)),
            ]),
          ),
        ),
      ),
    );
  }

  @override
  bool shouldRebuild(_MonthHeader old) => old.month != month || old.extent != extent || old.dark != dark;
}

// ---------------------------------------------------------------- the event ticket
/// One event as a concert ticket: name, place and dates on the main part; a date block and a barcode on the stub.
/// Leans toward your finger while held.
class EventTicket extends StatelessWidget {
  const EventTicket({super.key, required this.event, required this.onTap});
  final Map<String, dynamic> event;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final e = event;
    final cat = _s(e['category']);
    final c = eventColor(cat);
    final start = eventDay(e['start']);
    final end = eventDay(e['end']);
    final multi = start != null && end != null && end != start;
    final price = ticketText(e);
    final dark = context.dark;
    return Semantics(
      button: true,
      label: '${eventName(e)}, ${eventPlace(e)}, ${eventSpan(e)}',
      excludeSemantics: true,
      child: Tilt3D(
        maxAngle: .12,
        child: Ticket(
          axis: Axis.horizontal,
          onTap: onTap,
          elevation: 8,
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color.alphaBlend(c.withValues(alpha: dark ? .12 : .08), context.ticket), context.ticket],
          ),
          main: Padding(
            padding: const EdgeInsetsDirectional.fromSTEB(16, 14, 6, 14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Wrap(spacing: 6, runSpacing: 4, children: [
                _CatTag(cat),
                if (eventOnNow(e)) Pill(L('On now', 'شغّال دلوقتي'), color: DC.rose, solid: true),
              ]),
              const SizedBox(height: 8),
              Text(eventName(e), maxLines: 2, overflow: TextOverflow.ellipsis,
                  style: display(size: 17, weight: FontWeight.w700, color: context.ink, height: 1.25)),
              const SizedBox(height: 6),
              Row(children: [
                Text(flagOf(_s(e['country_code'])), style: const TextStyle(fontSize: 14)),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(eventPlace(e), maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: context.muted, fontSize: 13, fontWeight: FontWeight.w600)),
                ),
              ]),
              const SizedBox(height: 6),
              Text(eventSpan(e), style: TextStyle(color: context.ink, fontSize: 13, fontWeight: FontWeight.w700)),
              if (!datesConfirmed(e))
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text('⏳ ${L('Dates to be confirmed', 'المواعيد لسه هتتأكد')}',
                      style: const TextStyle(color: DC.amber, fontSize: 12, fontWeight: FontWeight.w700)),
                ),
              if (price != null)
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text('🎟 $price', maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: context.faint, fontSize: 12)),
                ),
            ]),
          ),
          // The stub: its own tint, clipped to the ticket's shape by the ticket itself.
          stub: SizedBox(
            width: 92,
            child: Container(
              color: c.withValues(alpha: dark ? .16 : .13),
              padding: const EdgeInsets.fromLTRB(10, 14, 10, 12),
              child: Column(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                if (start != null)
                  Column(children: [
                    Text(_mmm(start), style: mono(size: 12, color: c, spacing: 1.6)),
                    FittedBox(fit: BoxFit.scaleDown, child: Text(_dd(start), style: mono(size: 30, weight: FontWeight.w800, color: context.ink, height: 1.1))),
                    if (multi)
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Text('– ${end.month == start.month ? '' : '${_mmm(end)} '}${_dd(end)}',
                            style: mono(size: 11, color: context.muted)),
                      ),
                    Text('${start.year}', style: mono(size: 10, color: context.faint, weight: FontWeight.w600)),
                  ])
                else
                  Text(eventEmoji(cat), style: const TextStyle(fontSize: 26)),
                const SizedBox(height: 10),
                Barcode(_s(e['id']).isEmpty ? eventName(e) : _s(e['id']), height: 22, color: context.ink.withValues(alpha: .7)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

class _CatTag extends StatelessWidget {
  const _CatTag(this.cat, {this.onPhoto = false});
  final String cat;
  final bool onPhoto;

  @override
  Widget build(BuildContext context) {
    final c = eventColor(cat);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: onPhoto ? Colors.black.withValues(alpha: .5) : c.withValues(alpha: context.dark ? .18 : .14),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text('${eventEmoji(cat)} ${categoryLabel(cat)}',
          style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: onPhoto ? Colors.white : c)),
    );
  }
}

// ---------------------------------------------------------------- loading skeleton
class _SkeletonSliver extends StatefulWidget {
  const _SkeletonSliver();

  @override
  State<_SkeletonSliver> createState() => _SkeletonSliverState();
}

class _SkeletonSliverState extends State<_SkeletonSliver> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 900), lowerBound: .45)..repeat(reverse: true);

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bar = context.ink.withValues(alpha: context.dark ? .10 : .08);
    Widget line(double w, double h) => Container(
        width: w, height: h, margin: const EdgeInsets.only(bottom: 9),
        decoration: BoxDecoration(color: bar, borderRadius: BorderRadius.circular(6)));
    return SliverPadding(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
      sliver: SliverList.list(children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 14),
          child: Text(L("Checking the world's big events with Wikipedia and official sites…",
                  'بنراجع أكبر إيفنتات العالم مع ويكيبيديا والمواقع الرسمية…'),
              style: TextStyle(color: context.muted, fontSize: 13)),
        ),
        for (var i = 0; i < 4; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: RepaintBoundary(
              child: FadeTransition(
                opacity: _pulse,
                child: Ticket(
                  axis: Axis.horizontal,
                  elevation: 3,
                  main: Padding(
                    padding: const EdgeInsetsDirectional.fromSTEB(16, 16, 8, 8),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      line(70, 16), line(double.infinity, 16), line(150, 12), line(110, 12),
                    ]),
                  ),
                  stub: SizedBox(width: 92, height: 118, child: Center(child: line(40, 34))),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

/// The brand call-to-action for use ON a pass. Not BrandButton: that one wraps itself in an Opacity, which gets its
/// own layer and breaks the ticket's perforation painting; and this label shrinks to fit instead of overflowing.
class TicketButton extends StatelessWidget {
  const TicketButton({super.key, required this.label, required this.onTap, this.icon = Icons.flight_takeoff_rounded});
  final String label;
  final VoidCallback onTap;
  final IconData icon;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: BoxDecoration(
          gradient: DC.brand,
          borderRadius: BorderRadius.circular(16),
          boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .28), blurRadius: 22, offset: const Offset(0, 8))],
        ),
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: onTap,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 54),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Icon(icon, color: DC.onBrand, size: 20),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(label, textAlign: TextAlign.center,
                        style: const TextStyle(color: DC.onBrand, fontWeight: FontWeight.w800, fontSize: 16)),
                  ),
                ]),
              ),
            ),
          ),
        ),
      );
}

// ---------------------------------------------------------------- the detail sheet
/// The event as a full pass: its photo, why people go, the dates (and how sure they are), tickets, links, and
/// "Plan a trip to this event".
class EventDetailSheet extends StatelessWidget {
  const EventDetailSheet({super.key, required this.event, required this.onPlan});
  final Map<String, dynamic> event;
  final VoidCallback onPlan;

  @override
  Widget build(BuildContext context) {
    final e = event;
    final cat = _s(e['category']);
    final c = eventColor(cat);
    final why = isArabic && _s(e['why_ar']).isNotEmpty ? _s(e['why_ar']) : _s(e['why']);
    final desc = _s(e['description']);
    final quote = _s(e['dates_quote']);
    final website = _s(e['website']), wiki = _s(e['wikipedia']);
    final image = _s(e['image']);
    final price = ticketText(e);
    final confirmed = datesConfirmed(e);
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: .9,
      minChildSize: .45,
      maxChildSize: .96,
      builder: (ctx, sc) => ListView(
        controller: sc,
        padding: EdgeInsets.fromLTRB(14, 6, 14, 18 + MediaQuery.viewPaddingOf(ctx).bottom),
        children: [
          Center(
            child: Container(
              width: 42, height: 5, margin: const EdgeInsets.only(bottom: 12),
              decoration: BoxDecoration(color: Colors.white.withValues(alpha: .5), borderRadius: BorderRadius.circular(9)),
            ),
          ),
          // The photo is a print clipped to the pass, outside the ticket itself: the ticket paints its perforation
          // on its own canvas, which a fading image (its own layer) would break.
          Reveal(
            offset: 30,
            child: Transform.rotate(
              angle: isArabic ? .015 : -.015,
              child: Container(
                height: 210,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(22),
                  border: Border.all(color: context.ticket, width: 5),
                  boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .3), blurRadius: 18, offset: const Offset(0, 8))],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(17),
                  child: Stack(fit: StackFit.expand, children: [
                    PlacePhoto(
                      url: image.isNotEmpty ? image : null,
                      title: image.isEmpty ? _wikiTitle(wiki) : null,
                      emoji: eventEmoji(cat),
                      tint: c,
                    ),
                    DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [Colors.black.withValues(alpha: .3), Colors.transparent, Colors.transparent],
                        ),
                      ),
                    ),
                    PositionedDirectional(top: 12, start: 12, child: _CatTag(cat, onPhoto: true)),
                    if (eventOnNow(e))
                      PositionedDirectional(top: 12, end: 12, child: Pill(L('On now', 'شغّال دلوقتي'), color: DC.rose, solid: true)),
                  ]),
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Reveal(
            offset: 40,
            delay: const Duration(milliseconds: 90),
            child: Ticket(
              main: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(18, 16, 18, 8),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(eventName(e), style: display(size: 24, weight: FontWeight.w700, color: context.ink, height: 1.2)),
                    const SizedBox(height: 6),
                    Row(children: [
                      Text(flagOf(_s(e['country_code'])), style: const TextStyle(fontSize: 16)),
                      const SizedBox(width: 6),
                      Expanded(child: Text(eventPlace(e), style: TextStyle(color: context.muted, fontWeight: FontWeight.w600))),
                    ]),
                    const SizedBox(height: 16),
                    PassField(L('Dates', 'المواعيد'), eventSpan(e)),
                    const SizedBox(height: 8),
                    // Not a Pill: this one can be long and must wrap.
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: (confirmed ? DC.green : DC.amber).withValues(alpha: context.dark ? .16 : .14),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        confirmed
                            ? '✓ ${L('Confirmed dates', 'مواعيد مؤكدة')}'
                            : '⏳ ${L('Usual dates · to be confirmed', 'مواعيدها المعتادة · لسه هتتأكد')}',
                        style: TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w700, color: confirmed ? DC.green : DC.amber),
                      ),
                    ),
                    if (quote.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text('“$quote”', style: TextStyle(color: context.faint, fontSize: 12, fontStyle: FontStyle.italic)),
                    ],
                    if (why.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      MdText(why, color: context.ink),
                    ],
                    if (desc.isNotEmpty && desc != why) ...[
                      const SizedBox(height: 4),
                      Text(desc, style: TextStyle(color: context.faint, fontSize: 12.5)),
                    ],
                  ]),
                ),
              ]),
              stub: Padding(
                padding: const EdgeInsets.fromLTRB(18, 4, 18, 18),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  if (price != null) ...[PassField(L('Tickets', 'التذاكر'), price), const SizedBox(height: 14)],
                  TicketButton(label: L('Plan a trip to this event', 'خطّطلي رحلة ليها'), onTap: onPlan),
                  if (website.isNotEmpty || wiki.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Row(children: [
                      if (website.isNotEmpty)
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () => openLink(website),
                            icon: const Icon(Icons.open_in_new_rounded, size: 18),
                            label: Text(L('Official site', 'الموقع الرسمي'), maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                        ),
                      if (website.isNotEmpty && wiki.isNotEmpty) const SizedBox(width: 10),
                      if (wiki.isNotEmpty)
                        Expanded(
                          child: OutlinedButton(
                            onPressed: () => openLink(wiki),
                            child: Text(L('Wikipedia', 'ويكيبيديا'), maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                        ),
                    ]),
                  ],
                  const SizedBox(height: 16),
                  Barcode(_s(e['id']).isEmpty ? eventName(e) : _s(e['id']), height: 40),
                  const SizedBox(height: 6),
                  Center(child: Text(_s(e['id']).toUpperCase(), style: mono(size: 10, color: context.faint, spacing: 2))),
                ]),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
