import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api.dart';
import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';
import 'buddies_screen.dart';
import 'wallet_screen.dart';
import 'wizard_screen.dart' show currencies, interestKeys;

// ---------------------------------------------------------------- passport helpers (pure, tested)

// Arabic letters as a passport office writes them in Latin (Egyptian G for ج). Short vowels aren't written in
// Arabic, so the result is consonant-heavy - like many real MRZ lines.
const _arLatin = {
  'ا': 'A', 'أ': 'A', 'إ': 'I', 'آ': 'A', 'ب': 'B', 'ت': 'T', 'ث': 'TH', 'ج': 'G', 'ح': 'H', 'خ': 'KH', 'د': 'D',
  'ذ': 'Z', 'ر': 'R', 'ز': 'Z', 'س': 'S', 'ش': 'SH', 'ص': 'S', 'ض': 'D', 'ط': 'T', 'ظ': 'Z', 'ع': 'A', 'غ': 'GH',
  'ف': 'F', 'ق': 'K', 'ك': 'K', 'ل': 'L', 'م': 'M', 'ن': 'N', 'ه': 'H', 'و': 'W', 'ي': 'Y', 'ى': 'A', 'ة': 'A',
  'ء': '', 'ؤ': '', 'ئ': '',
};

/// A name as a machine-readable zone writes it: A-Z and 0-9 only (Arabic transliterated), word breaks as '<'.
String mrzName(String name) {
  final b = StringBuffer();
  for (final ch in name.trim().toUpperCase().characters) {
    final c = ch.codeUnitAt(0);
    if ((c >= 65 && c <= 90) || (c >= 48 && c <= 57)) {
      b.write(ch);
    } else if (_arLatin.containsKey(ch)) {
      b.write(_arLatin[ch]);
    } else if (c >= 0x0660 && c <= 0x0669) {
      b.writeCharCode(0x30 + c - 0x0660);
    } else if (ch.trim().isEmpty || ch == '-' || ch == "'" || ch == '.') {
      b.write('<');
    }
  }
  return b.toString().replaceAll(RegExp('<+'), '<').replaceAll(RegExp(r'^<|<$'), '');
}

/// The ICAO 9303 check digit (weights 7-3-1; letters count 10..35, '<' counts 0).
String mrzCheck(String s) {
  const w = [7, 3, 1];
  var sum = 0;
  for (var i = 0; i < s.length; i++) {
    final c = s.codeUnitAt(i);
    final v = c >= 48 && c <= 57 ? c - 48 : (c >= 65 && c <= 90 ? c - 55 : 0);
    sum += v * w[i % 3];
  }
  return '${sum % 10}';
}

/// A stable 9-character "passport number" from the account id.
String passportNo(String id) {
  final a = id.toUpperCase().replaceAll(RegExp('[^A-Z0-9]'), '');
  final tail = a.length >= 7 ? a.substring(a.length - 7) : a.padLeft(7, '0');
  return 'DL$tail';
}

String _pad(String s, int n) => s.length >= n ? s.substring(0, n) : s + '<' * (n - s.length);

/// The two 44-character lines at the foot of the identity page.
List<String> mrzLines({required String name, required String id, DateTime? since}) {
  final parts = mrzName(name).split('<').where((p) => p.isNotEmpty).toList();
  if (parts.isEmpty) parts.add('TRAVELLER');
  final surname = parts.length > 1 ? parts.last : parts.first;
  final given = parts.length > 1 ? parts.sublist(0, parts.length - 1).join('<') : '';
  final no = passportNo(id);
  final d = since == null
      ? '<<<<<<'
      : '${(since.year % 100).toString().padLeft(2, '0')}${since.month.toString().padLeft(2, '0')}${since.day.toString().padLeft(2, '0')}';
  final body = '$no${mrzCheck(no)}DLI$d${mrzCheck(d)}';
  return [_pad('P<DLI$surname<<$given', 44), '${_pad(body, 43)}${mrzCheck(body)}'];
}

/// One passport stamp: a city the traveller planned (past = visited, future = upcoming).
class StampData {
  const StampData({required this.city, required this.code, required this.label, required this.color,
      required this.angle, required this.dx, required this.dy, required this.upcoming});
  final String city, code, label;
  final Color color;
  final double angle, dx, dy;
  final bool upcoming;
}

const _stampInks = [DC.rose, DC.tealDeep, DC.violet, DC.amber, DC.sky, DC.green, DC.coral];
const _months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

/// The stamps page, from the trips list: one stamp per city of a planned trip (the first time it was planned),
/// each with its own ink, tilt and nudge - random-looking but the same every time for the same city.
List<StampData> passportStamps(List<dynamic> trips, {DateTime? today, int max = 24}) {
  final now = today ?? DateTime.now();
  final seen = <String>{};
  final out = <StampData>[];
  final planned = trips.whereType<Map>().where((t) => t['status'] == 'planned').toList()
    ..sort((a, b) => '${a['start_date'] ?? ''}'.compareTo('${b['start_date'] ?? ''}'));
  for (final t in planned) {
    final start = DateTime.tryParse('${t['start_date'] ?? ''}');
    for (final c in (t['cities'] as List? ?? const [])) {
      final city = '$c'.trim();
      if (city.isEmpty || !seen.add(city.toLowerCase())) continue;
      final h = city.toLowerCase().codeUnits.fold<int>(17, (a, x) => (a * 31 + x) & 0x7fffffff);
      final latin = mrzName(city).replaceAll('<', '');
      final code = (latin.length >= 3 ? latin.substring(0, 3) : (latin.isNotEmpty ? latin : city.characters.take(3).toString()));
      final when = start == null ? '' : ' · ${_months[start.month - 1]} ${start.year}';
      out.add(StampData(
        city: city,
        code: code,
        label: '$city$when',
        color: _stampInks[h % _stampInks.length],
        angle: ((h >> 3) % 61 - 30) / 100,
        dx: ((h >> 7) % 13 - 6).toDouble(),
        dy: ((h >> 11) % 13 - 6).toDouble(),
        upcoming: start != null && !start.isBefore(DateTime(now.year, now.month, now.day)),
      ));
      if (out.length >= max) return out;
    }
  }
  return out;
}

// ---------------------------------------------------------------- the passport tab

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, required this.state});
  final AppState state;
  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Future<Map<String, dynamic>?>? _dash;
  String? _dashFor;
  bool _wasActive = false;
  int _visit = 0; // goes up each time the tab is opened: the stamps land again
  bool? _online; // the server's reachability, checked when the tab opens

  AppState get st => widget.state;

  Future<Map<String, dynamic>?> _loadDash() async {
    try {
      return await st.api.get('/api/me/dashboard') as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  Future<void> _ping() async {
    final ok = await st.ping();
    if (mounted) setState(() => _online = ok);
  }

  @override
  Widget build(BuildContext context) {
    final u = st.user;
    final active = st.tab == Tabs.me;
    if (active && !_wasActive) {
      _visit++;
      if (u != null) _dash = _loadDash(); // trips planned since last time get their stamps
      scheduleMicrotask(_ping);
    }
    _wasActive = active;
    if (u != null && (_dash == null || _dashFor != u['id'])) {
      _dashFor = u['id'] as String?;
      _dash = _loadDash();
    }
    if (u == null) _dashFor = null;

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: EdgeInsets.fromLTRB(16, 8, 16, context.dockSpace + 8),
          children: [
            _Header(state: st),
            const SizedBox(height: 14),
            if (u == null)
              _PassportBook(onAuth: (up) => showAuthSheet(context, st, signUp: up))
            else
              ..._passport(u),
            _groupTitle(tr('settings')),
            _settings(u),
            if (u != null) ...[
              _groupTitle(tr('profile')),
              _account(),
            ],
            _groupTitle(tr('about')),
            _Page(
              child: Row(children: [
                const Text('🧠', style: TextStyle(fontSize: 26)),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('appName'), style: display(size: 16)),
                    const SizedBox(height: 2),
                    Text(tr('howItWorks'), style: TextStyle(color: context.muted, fontSize: 13, height: 1.4)),
                  ]),
                ),
              ]),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _passport(Map<String, dynamic> u) => [
        Reveal(child: _IdentityPage(user: u)),
        const SizedBox(height: 14),
        FutureBuilder<Map<String, dynamic>?>(
          future: _dash,
          builder: (_, s) {
            final stats = s.data?['stats'] as Map<String, dynamic>?;
            final trips = (s.data?['trips'] as List?) ?? st.trips;
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Reveal(delay: const Duration(milliseconds: 80), child: _StatsBoard(stats: stats)),
              const SizedBox(height: 14),
              _StampsPage(key: ValueKey(_visit), stamps: passportStamps(trips), loading: s.connectionState != ConnectionState.done),
            ]);
          },
        ),
        const SizedBox(height: 14),
        _TastePage(
          taste: ((st.recs?['taste'] as List?) ?? const []).whereType<Map>().toList(),
          interests: ((u['prefs']?['interests'] as List?) ?? const []).map((e) => '$e').toList(),
          onEdit: _editInterests,
        ),
        const SizedBox(height: 14),
        _LinkPass(
          emoji: '🎫',
          title: tr('tripsTitle'),
          subtitle: L('Every trip you planned, as a pass', 'كل رحلة خططتها، على شكل تذكرة'),
          color: DC.teal,
          count: st.trips.length,
          onTap: () => Navigator.of(context).push(passRoute(WalletScreen(state: st))),
        ),
        const SizedBox(height: 10),
        _LinkPass(
          emoji: '🧑‍🤝‍🧑',
          title: L('My travel groups', 'جروبات السفر بتاعتي'),
          subtitle: L('Travellers in the same city at the same time', 'مسافرين في نفس المدينة في نفس الوقت'),
          color: DC.violet,
          onTap: () => Navigator.of(context).push(passRoute(BuddiesScreen(state: st))),
        ),
      ];

  Widget _groupTitle(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(6, 24, 6, 8),
        child: Text(t.toUpperCase(), style: TextStyle(color: context.muted, fontWeight: FontWeight.w800, fontSize: 12, letterSpacing: 1.2)),
      );

  // ---------------------------------------------------------------- settings
  Widget _settings(Map<String, dynamic>? u) {
    final prefs = (u?['prefs'] as Map?) ?? const {};
    final home = (prefs['home_city'] as String?) ?? '';
    final ints = ((prefs['interests'] as List?) ?? const []).map((i) => '${DC.emoji[i] ?? ''} ${tr('int.$i')}').join('  ');
    return _Page(
      padding: EdgeInsets.zero,
      child: Column(children: [
        _Row(
          icon: Icons.translate_rounded,
          title: tr('language'),
          trailing: _Segments<String>(
            value: st.lang,
            options: const [('ar', 'عربي'), ('en', 'EN')],
            onChanged: st.setLang,
          ),
        ),
        _Row(
          icon: Icons.dark_mode_outlined,
          title: tr('theme'),
          below: _Segments<ThemeMode>(
            value: st.themeMode,
            expand: true,
            options: [(ThemeMode.system, tr('themeSystem')), (ThemeMode.light, tr('themeLight')), (ThemeMode.dark, tr('themeDark'))],
            onChanged: st.setTheme,
          ),
        ),
        if (u != null) ...[
          _Row(
            icon: Icons.person_outline,
            title: tr('name'),
            subtitle: '${u['name'] ?? ''}',
            onTap: () => _editText(tr('name'), '${u['name'] ?? ''}', (v) async {
              if (v.isEmpty) return false;
              await st.updateProfile({'name': v});
              return true;
            }),
          ),
          _Row(
            icon: Icons.flight_takeoff_rounded,
            title: tr('homeCity'),
            subtitle: home.isNotEmpty ? home : '—',
            onTap: () => _editText(tr('homeCity'), home, (v) async {
              await st.updateProfile({'home_city': v});
              return true;
            }),
          ),
          _Row(
            icon: Icons.payments_outlined,
            title: tr('currency'),
            trailing: DropdownButton<String>(
              value: currencies.contains(prefs['currency']) ? prefs['currency'] as String : 'USD',
              underline: const SizedBox(),
              borderRadius: BorderRadius.circular(16),
              style: mono(size: 14, color: context.ink),
              items: [for (final c in currencies) DropdownMenuItem(value: c, child: Text(c))],
              onChanged: (c) async {
                if (c == null) return;
                try {
                  await st.updateProfile({'currency': c});
                  if (mounted) toast(context, tr('saved'));
                } on ApiException catch (e) {
                  if (mounted) toast(context, authError(e));
                }
              },
            ),
          ),
          _Row(
            icon: Icons.favorite_border_rounded,
            title: tr('interests'),
            subtitle: ints.trim().isEmpty ? '—' : ints,
            onTap: _editInterests,
          ),
        ],
        _Row(
          icon: Icons.dns_outlined,
          title: tr('server'),
          subtitle: st.baseUrl,
          ltrSubtitle: true,
          trailing: _OnlineDot(online: _online),
          onTap: _editServer,
          last: true,
        ),
      ]),
    );
  }

  Widget _account() => _Page(
        padding: EdgeInsets.zero,
        child: Column(children: [
          _Row(icon: Icons.lock_outline_rounded, title: tr('changePassword'), onTap: _changePassword),
          _Row(
            icon: Icons.logout_rounded,
            title: tr('signOut'),
            onTap: () async {
              await st.signOut();
              if (mounted) toast(context, tr('signedOut'));
            },
          ),
          _Row(icon: Icons.delete_forever_rounded, title: tr('deleteAccount'), danger: true, onTap: _deleteAccount, last: true),
        ]),
      );

  /// A one-field sheet; [save] returns false to keep it open (e.g. an empty name).
  Future<void> _editText(String title, String value, Future<bool> Function(String) save) async {
    final c = TextEditingController(text: value);
    String? err;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (s) => StatefulBuilder(
        builder: (s, set) => _SheetBody(
          title: title,
          children: [
            TextField(controller: c, autofocus: true, decoration: InputDecoration(errorText: err)),
            const SizedBox(height: 18),
            BrandButton(
              label: tr('save'),
              onTap: () async {
                try {
                  final ok = await save(c.text.trim());
                  if (!ok) return set(() => err = tr('eName'));
                  if (s.mounted) Navigator.pop(s);
                  if (mounted) toast(context, tr('saved'));
                } on ApiException catch (e) {
                  set(() => err = authError(e));
                }
              },
            ),
          ],
        ),
      ),
    );
    c.dispose();
  }

  Future<void> _editInterests() async {
    final picked = {...((st.user?['prefs']?['interests'] as List?) ?? []).cast<String>()};
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (s) => StatefulBuilder(
        builder: (s, set) => _SheetBody(
          title: tr('interests'),
          children: [
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final k in interestKeys)
                FilterChip(
                  label: Text('${DC.emoji[k]} ${tr('int.$k')}'),
                  selected: picked.contains(k),
                  selectedColor: (DC.tag[k] ?? DC.teal).withValues(alpha: .25),
                  onSelected: (v) => set(() => v ? picked.add(k) : picked.remove(k)),
                ),
            ]),
            const SizedBox(height: 18),
            BrandButton(label: tr('save'), onTap: () => Navigator.pop(s, true)),
          ],
        ),
      ),
    );
    if (ok == true) {
      try {
        await st.updateProfile({'interests': picked.toList()});
        if (mounted) toast(context, tr('saved'));
      } on ApiException catch (e) {
        if (mounted) toast(context, authError(e));
      }
    }
  }

  Future<void> _editServer() async {
    final c = TextEditingController(text: st.baseUrl);
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (s) => _SheetBody(
        title: tr('server'),
        children: [
          Text(tr('serverSub'), style: TextStyle(color: context.muted, fontSize: 13)),
          const SizedBox(height: 12),
          TextField(controller: c, keyboardType: TextInputType.url, textDirection: TextDirection.ltr, autofocus: true,
              style: mono(size: 14, weight: FontWeight.w500, color: context.ink)),
          const SizedBox(height: 18),
          BrandButton(label: tr('save'), onTap: () => Navigator.pop(s, true)),
        ],
      ),
    );
    final url = c.text;
    c.dispose();
    if (ok == true) {
      setState(() => _online = null);
      final reachable = await st.setBaseUrl(url);
      if (!mounted) return;
      setState(() => _online = reachable);
      toast(context, reachable ? tr('serverOk') : tr('serverBad'));
      if (reachable) {
        await st.refreshMe();
        st.refreshHome();
      }
    }
  }

  Future<void> _changePassword() async {
    final cur = TextEditingController(), next = TextEditingController();
    String? err;
    var busy = false;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => _SheetBody(
          title: tr('changePassword'),
          children: [
            TextField(controller: cur, obscureText: true, textDirection: TextDirection.ltr,
                decoration: InputDecoration(labelText: tr('current'), prefixIcon: const Icon(Icons.lock_outline))),
            const SizedBox(height: 12),
            TextField(controller: next, obscureText: true, textDirection: TextDirection.ltr,
                decoration: InputDecoration(labelText: tr('newPass'), helperText: tr('passHint'), prefixIcon: const Icon(Icons.lock_outline))),
            if (err != null) _ErrorBox(err!),
            const SizedBox(height: 18),
            BrandButton(
              label: tr('save'),
              busy: busy,
              onTap: () async {
                final p = passwordProblem(next.text);
                if (p != null) return set(() => err = p);
                set(() => busy = true);
                try {
                  await st.changePassword(cur.text, next.text);
                  if (d.mounted) Navigator.pop(d);
                  if (mounted) toast(context, tr('passChanged'));
                } on ApiException catch (e) {
                  if (d.mounted) set(() => err = authError(e));
                } finally {
                  if (d.mounted) set(() => busy = false);
                }
              },
            ),
          ],
        ),
      ),
    );
    cur.dispose();
    next.dispose();
  }

  Future<void> _deleteAccount() async {
    final pw = TextEditingController();
    String? err;
    var busy = false;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => _SheetBody(
          title: tr('deleteAccount'),
          children: [
            Text(tr('deleteAccountSub'), style: TextStyle(color: context.muted, height: 1.4)),
            const SizedBox(height: 12),
            TextField(controller: pw, obscureText: true, textDirection: TextDirection.ltr,
                decoration: InputDecoration(labelText: tr('password'), prefixIcon: const Icon(Icons.lock_outline))),
            if (err != null) _ErrorBox(err!),
            const SizedBox(height: 18),
            SizedBox(
              height: 52,
              child: FilledButton(
                style: FilledButton.styleFrom(backgroundColor: DC.rose, foregroundColor: Colors.white),
                onPressed: busy
                    ? null
                    : () async {
                        set(() => busy = true);
                        try {
                          await st.deleteAccount(pw.text);
                          if (d.mounted) Navigator.pop(d);
                        } on ApiException catch (e) {
                          if (d.mounted) set(() => err = authError(e));
                        } finally {
                          if (d.mounted) set(() => busy = false);
                        }
                      },
                child: Text(tr('delete')),
              ),
            ),
          ],
        ),
      ),
    );
    pw.dispose();
  }
}

// ---------------------------------------------------------------- pieces

class _Header extends StatelessWidget {
  const _Header({required this.state});
  final AppState state;
  @override
  Widget build(BuildContext context) {
    final u = state.user;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(L('TRAVEL DOCUMENT', 'وثيقة سفر'),
                style: TextStyle(fontSize: 11, letterSpacing: 2, fontWeight: FontWeight.w800, color: context.faint)),
            Text(tr('tabMe'), style: display(size: 30, color: context.ink, height: 1.15)),
          ]),
        ),
        if (u != null)
          Stamp(label: 'DALILI · ${DateTime.now().year} · ', center: '✈', color: DC.teal.withValues(alpha: .7), size: 56, angle: .25),
      ]),
    );
  }
}

/// A sheet of passport paper: cream by day, dark glass at night.
class _Page extends StatelessWidget {
  const _Page({required this.child, this.padding = const EdgeInsets.all(16)});
  final Widget child;
  final EdgeInsets padding;
  @override
  Widget build(BuildContext context) => Container(
        padding: padding,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: context.ticket,
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: context.ticketEdge),
          boxShadow: [
            BoxShadow(color: (context.dark ? Colors.black : const Color(0xFF1C3460)).withValues(alpha: context.dark ? .35 : .08),
                blurRadius: 18, offset: const Offset(0, 8)),
          ],
        ),
        child: child,
      );
}

class _Row extends StatelessWidget {
  const _Row({required this.icon, required this.title, this.subtitle, this.trailing, this.below, this.onTap,
      this.danger = false, this.ltrSubtitle = false, this.last = false});
  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final Widget? below;
  final VoidCallback? onTap;
  final bool danger, ltrSubtitle, last;

  @override
  Widget build(BuildContext context) {
    final color = danger ? DC.rose : context.ink;
    return InkWell(
      onTap: onTap,
      child: Container(
        constraints: const BoxConstraints(minHeight: 56),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(border: last ? null : Border(bottom: BorderSide(color: context.line))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Container(
              width: 36,
              height: 36,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: (danger ? DC.rose : DC.teal).withValues(alpha: context.dark ? .14 : .12),
                borderRadius: BorderRadius.circular(11),
              ),
              child: Icon(icon, size: 19, color: danger ? DC.rose : (context.dark ? DC.teal : DC.tealDeep)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: color)),
                if (subtitle != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(subtitle!, maxLines: 2, overflow: TextOverflow.ellipsis,
                        textDirection: ltrSubtitle ? TextDirection.ltr : null,
                        textAlign: TextAlign.start,
                        style: ltrSubtitle
                            ? mono(size: 12, weight: FontWeight.w500, color: context.muted)
                            : TextStyle(fontSize: 13, color: context.muted)),
                  ),
              ]),
            ),
            if (trailing != null) ...[const SizedBox(width: 8), trailing!],
            if (trailing == null && onTap != null) Icon(Icons.chevron_right, color: context.faint),
          ]),
          if (below != null) Padding(padding: const EdgeInsets.only(top: 10), child: below!),
        ]),
      ),
    );
  }
}

/// A compact segmented control drawn like pass tabs (the Material one is too wide for three Arabic labels).
class _Segments<T> extends StatelessWidget {
  const _Segments({required this.value, required this.options, required this.onChanged, this.expand = false});
  final T value;
  final List<(T, String)> options;
  final ValueChanged<T> onChanged;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    Widget seg((T, String) o) {
      final on = o.$1 == value;
      final child = Pressable(
        onTap: () => onChanged(o.$1),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOut,
          constraints: const BoxConstraints(minHeight: 44, minWidth: 48),
          padding: const EdgeInsets.symmetric(horizontal: 12),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            gradient: on ? DC.brand : null,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(o.$2, maxLines: 1, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13, color: on ? DC.onBrand : context.muted)),
        ),
      );
      return expand ? Expanded(child: child) : child;
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(color: context.card2, borderRadius: BorderRadius.circular(15), border: Border.all(color: context.line)),
      child: Row(mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min, children: [for (final o in options) seg(o)]),
    );
  }
}

class _OnlineDot extends StatelessWidget {
  const _OnlineDot({required this.online});
  final bool? online;
  @override
  Widget build(BuildContext context) {
    final c = online == null ? context.faint : (online! ? DC.green : DC.rose);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        width: 9,
        height: 9,
        decoration: BoxDecoration(color: c, shape: BoxShape.circle,
            boxShadow: [if (online != null) BoxShadow(color: c.withValues(alpha: .6), blurRadius: 8)]),
      ),
      const SizedBox(width: 6),
      Text(online == null ? '…' : (online! ? tr('serverOk') : tr('serverBad')),
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: c)),
    ]);
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 12),
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: DC.rose.withValues(alpha: .12), borderRadius: BorderRadius.circular(12)),
          child: Text(text, style: const TextStyle(color: DC.rose, fontWeight: FontWeight.w700)),
        ),
      );
}

/// The common body of this tab's bottom sheets: a title, then the fields, lifted above the keyboard.
class _SheetBody extends StatelessWidget {
  const _SheetBody({required this.title, required this.children});
  final String title;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom + MediaQuery.viewPaddingOf(context).bottom),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(title, style: display(size: 22, color: context.ink)),
            const SizedBox(height: 16),
            ...children,
          ]),
        ),
      );
}

// ---------------------------------------------------------------- guest: the closed passport

/// A closed passport you can tilt; tap it and the cover swings open on its spine, showing the sign-in page.
class _PassportBook extends StatefulWidget {
  const _PassportBook({required this.onAuth});
  final void Function(bool signUp) onAuth;
  @override
  State<_PassportBook> createState() => _PassportBookState();
}

class _PassportBookState extends State<_PassportBook> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 950));

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  void _toggle() {
    HapticFeedback.mediumImpact();
    _c.value < .5 ? _c.animateTo(1, curve: Curves.easeInOutCubic) : _c.animateTo(0, curve: Curves.easeInOutCubic);
  }

  @override
  Widget build(BuildContext context) {
    final rtl = Directionality.of(context) == TextDirection.rtl;
    return LayoutBuilder(builder: (context, c) {
      final w = math.min(c.maxWidth, 380.0);
      return Center(
        child: SizedBox(
          width: w,
          child: AnimatedBuilder(
            animation: _c,
            builder: (context, _) {
              final v = _c.value;
              final open = v > .5;
              return Stack(children: [
                // The page under the cover (sizes the book; the cover lies over it).
                IgnorePointer(
                  ignoring: !open,
                  child: Opacity(opacity: (.35 + v * .65).clamp(0, 1), child: _GuestPage(minHeight: w * 1.25, onAuth: widget.onAuth, onClose: _toggle)),
                ),
                if (v < .999)
                  Positioned.fill(
                    child: IgnorePointer(
                      ignoring: open,
                      child: Transform(
                        // The spine is on the reading side's start: the left in English, the right in Arabic.
                        alignment: rtl ? Alignment.centerRight : Alignment.centerLeft,
                        transform: perspective()..rotateY((rtl ? 1 : -1) * v * math.pi * .55),
                        child: Opacity(
                          opacity: (1 - math.max(0, v - .7) / .3).clamp(0, 1),
                          child: Float(amount: 4, child: Tilt3D(maxAngle: .14, child: RepaintBoundary(child: SizedBox.expand(child: _Cover(onTap: _toggle))))),
                        ),
                      ),
                    ),
                  ),
              ]);
            },
          ),
        ),
      );
    });
  }
}

class _Cover extends StatelessWidget {
  const _Cover({required this.onTap});
  final VoidCallback onTap;
  static const _gold = Color(0xFFE8C77A);

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(22),
            gradient: const LinearGradient(
              colors: [Color(0xFF14365A), Color(0xFF0C2340), Color(0xFF081A31)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .45), blurRadius: 30, offset: const Offset(0, 16))],
          ),
          child: Stack(children: [
            // the spine's crease
            PositionedDirectional(
              start: 14,
              top: 0,
              bottom: 0,
              child: Container(width: 2, color: Colors.black.withValues(alpha: .28)),
            ),
            Positioned.fill(child: RepaintBoundary(child: CustomPaint(painter: _GuillochePainter(_gold.withValues(alpha: .07))))),
            Padding(
              padding: const EdgeInsets.fromLTRB(28, 28, 28, 24),
              child: Column(children: [
                Text(L('PASSPORT', 'جواز سفر'), style: display(size: 22, color: _gold, spacing: isArabic ? 0 : 6)),
                const SizedBox(height: 2),
                Text(isArabic ? 'PASSPORT' : 'جواز سفر', style: display(size: 13, color: _gold.withValues(alpha: .7))),
                const Spacer(),
                Container(
                  width: 112,
                  height: 112,
                  decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: _gold, width: 2)),
                  alignment: Alignment.center,
                  child: Container(
                    width: 88,
                    height: 88,
                    decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: _gold.withValues(alpha: .6))),
                    alignment: Alignment.center,
                    child: Transform.rotate(angle: math.pi / 4, child: const Icon(Icons.flight_rounded, color: _gold, size: 46)),
                  ),
                ),
                const Spacer(),
                Text(tr('appName').toUpperCase(), style: display(size: 26, color: _gold, spacing: isArabic ? 0 : 8)),
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(borderRadius: BorderRadius.circular(999), border: Border.all(color: _gold.withValues(alpha: .5))),
                  child: Text(L('Tap to open', 'دوس عشان تفتحه'),
                      style: TextStyle(color: _gold.withValues(alpha: .9), fontWeight: FontWeight.w700, fontSize: 13)),
                ),
              ]),
            ),
          ]),
        ),
      );
}

class _GuestPage extends StatelessWidget {
  const _GuestPage({required this.minHeight, required this.onAuth, required this.onClose});
  final double minHeight;
  final void Function(bool signUp) onAuth;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) => Container(
        constraints: BoxConstraints(minHeight: minHeight),
        decoration: BoxDecoration(
          color: context.ticket,
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: context.ticketEdge),
        ),
        child: Stack(children: [
          Positioned.fill(child: RepaintBoundary(child: CustomPaint(painter: _GuillochePainter(DC.teal.withValues(alpha: context.dark ? .05 : .08))))),
          Padding(
            padding: const EdgeInsets.fromLTRB(22, 18, 22, 22),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Text(L('PAGE 1', 'صفحة ١'), style: mono(size: 11, color: context.faint, spacing: 1.5)),
                const Spacer(),
                SizedBox(
                  width: 44,
                  height: 44,
                  child: IconButton(onPressed: onClose, icon: Icon(Icons.close_rounded, color: context.muted, size: 20)),
                ),
              ]),
              const SizedBox(height: 4),
              Center(child: Stamp(label: L('Not yet stamped · ', 'لسه من غير ختم · '), center: '?', color: DC.rose.withValues(alpha: .75), size: 92, angle: -.2)),
              const SizedBox(height: 18),
              Text(tr('guestTitle'), textAlign: TextAlign.center, style: display(size: 24, color: context.ink, height: 1.2)),
              const SizedBox(height: 8),
              Text(tr('guestSub'), textAlign: TextAlign.center, style: TextStyle(color: context.muted, height: 1.45)),
              const SizedBox(height: 22),
              BrandButton(label: tr('signUp'), icon: Icons.person_add_alt_1_rounded, onTap: () => onAuth(true)),
              const SizedBox(height: 10),
              SizedBox(height: 50, child: OutlinedButton(onPressed: () => onAuth(false), child: Text(tr('signIn')))),
            ]),
          ),
        ]),
      );
}

/// The fine wavy security lines on passport paper. Static: painted once into its own layer.
class _GuillochePainter extends CustomPainter {
  _GuillochePainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = color;
    for (var i = 0; i < 14; i++) {
      final path = Path();
      final y0 = size.height * (i + .5) / 14;
      for (var x = 0.0; x <= size.width; x += 6) {
        final y = y0 + math.sin(x / 26 + i * .7) * 9 + math.sin(x / 9 + i) * 2.5;
        x == 0 ? path.moveTo(x, y) : path.lineTo(x, y);
      }
      canvas.drawPath(path, p);
    }
  }

  @override
  bool shouldRepaint(_GuillochePainter old) => old.color != color;
}

// ---------------------------------------------------------------- signed in: the identity page

class _IdentityPage extends StatelessWidget {
  const _IdentityPage({required this.user});
  final Map<String, dynamic> user;

  @override
  Widget build(BuildContext context) {
    final name = '${user['name'] ?? ''}'.trim();
    final since = DateTime.tryParse('${user['created_at'] ?? ''}');
    final home = '${user['prefs']?['home_city'] ?? ''}'.trim();
    final id = '${user['id'] ?? user['email'] ?? name}';
    final mrz = mrzLines(name: name, id: id, since: since);
    final initial = name.isEmpty ? '✈' : name.characters.first.toUpperCase();
    return Tilt3D(
      maxAngle: .12,
      child: RepaintBoundary(
        child: Container(
          decoration: BoxDecoration(
            color: context.ticket,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: context.ticketEdge),
            boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .4 : .1), blurRadius: 24, offset: const Offset(0, 12))],
          ),
          clipBehavior: Clip.antiAlias,
          child: Stack(children: [
            Positioned.fill(child: CustomPaint(painter: _GuillochePainter(DC.violet.withValues(alpha: context.dark ? .06 : .09)))),
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: const BoxDecoration(gradient: DC.brand),
                child: Row(children: [
                  Expanded(
                    child: Text(L('PASSPORT · TRAVEL WALLET', 'جواز سفر · محفظة السفر'), maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 11, letterSpacing: 1.4, fontWeight: FontWeight.w900, color: DC.onBrand)),
                  ),
                  Text('DLI', style: mono(size: 12, color: DC.onBrand, spacing: 2)),
                ]),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  // the photo
                  Container(
                    width: 84,
                    height: 104,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      gradient: const LinearGradient(colors: [Color(0xFF1B3B66), Color(0xFF3A2352)], begin: Alignment.topLeft, end: Alignment.bottomRight),
                      border: Border.all(color: context.ticketEdge),
                    ),
                    alignment: Alignment.center,
                    child: Stack(alignment: Alignment.center, children: [
                      Container(
                        width: 58,
                        height: 58,
                        decoration: const BoxDecoration(shape: BoxShape.circle, gradient: SweepGradient(colors: [DC.teal, DC.violet, DC.amber, DC.teal])),
                        alignment: Alignment.center,
                        child: Text(initial, style: display(size: 26, weight: FontWeight.w800, color: const Color(0xFF06101C))),
                      ),
                      // holographic sheen
                      Positioned.fill(
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(12),
                            gradient: LinearGradient(
                              colors: [Colors.transparent, Colors.white.withValues(alpha: .16), Colors.transparent],
                              stops: const [.35, .5, .65],
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                            ),
                          ),
                        ),
                      ),
                    ]),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      PassField(L('Name', 'الاسم'), name.isEmpty ? '—' : name, big: true),
                      const SizedBox(height: 10),
                      PassField(L('Passport no.', 'رقم الجواز'), passportNo(id)),
                      const SizedBox(height: 10),
                      Row(children: [
                        Expanded(child: PassField(L('Member since', 'معانا من'), since == null ? '—' : fmtDate(since.toIso8601String(), year: true))),
                        const SizedBox(width: 8),
                        Expanded(child: PassField(L('Home city', 'مدينتك'), home.isEmpty ? '—' : home)),
                      ]),
                    ]),
                  ),
                ]),
              ),
              if ((user['email'] as String?)?.isNotEmpty == true)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                  child: Text(user['email'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, textDirection: TextDirection.ltr,
                      textAlign: TextAlign.start, style: TextStyle(color: context.muted, fontSize: 12.5)),
                ),
              // the machine-readable zone
              Container(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
                color: context.dark ? Colors.white.withValues(alpha: .04) : const Color(0x0D1C3460),
                child: Directionality(
                  textDirection: TextDirection.ltr,
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      for (final l in mrz) Text(l, style: mono(size: 13, weight: FontWeight.w600, color: context.ink.withValues(alpha: .8), spacing: 1.2, height: 1.5)),
                    ]),
                  ),
                ),
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}

/// The traveller's numbers on a departures board: each value flips in.
class _StatsBoard extends StatelessWidget {
  const _StatsBoard({required this.stats});
  final Map<String, dynamic>? stats;

  @override
  Widget build(BuildContext context) {
    final s = stats ?? const {};
    Widget cell(Object? v, String k, int i) => Expanded(
          child: Column(children: [
            SizedBox(
              height: 34,
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: SplitFlap('${v ?? '–'}', style: mono(size: 20, color: const Color(0xFFFFD27A)), delay: Duration(milliseconds: 120 * i),
                    tileColor: const Color(0xFF151C2E)),
              ),
            ),
            const SizedBox(height: 6),
            Text(tr(k), maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xFF93A3C2), fontSize: 11, fontWeight: FontWeight.w700)),
          ]),
        );
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 12, 10, 12),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0F1C),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withValues(alpha: .08)),
      ),
      child: Row(children: [
        cell(s['planned'], 'stTrips', 0),
        cell(s['countries'], 'stCountries', 1),
        cell(s['days'], 'stDays', 2),
        cell(s['avg_score'], 'stScore', 3),
      ]),
    );
  }
}

/// The visas page: one stamp per city, pressed down one after another.
class _StampsPage extends StatelessWidget {
  const _StampsPage({super.key, required this.stamps, required this.loading});
  final List<StampData> stamps;
  final bool loading;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: context.ticket,
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: context.ticketEdge),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(children: [
          Positioned.fill(child: RepaintBoundary(child: CustomPaint(painter: _GuillochePainter(DC.rose.withValues(alpha: context.dark ? .05 : .07))))),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Expanded(child: Text(L('Visas & stamps', 'التأشيرات والأختام'), style: display(size: 17, color: context.ink))),
                if (stamps.isNotEmpty) Text('${stamps.length}', style: mono(size: 13, color: context.faint)),
              ]),
              const SizedBox(height: 12),
              if (stamps.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Column(children: [
                    Opacity(
                      opacity: .35,
                      child: Stamp(label: L('Your first trip · ', 'أول رحلة ليك · '), center: '✈', color: context.muted, size: 84, angle: -.15),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      loading ? '…' : L('Your first stamp lands here when you plan a trip.', 'أول ختم هينزل هنا لما تخطط رحلة.'),
                      textAlign: TextAlign.center,
                      style: TextStyle(color: context.muted),
                    ),
                  ]),
                )
              else
                Wrap(
                  alignment: WrapAlignment.center,
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (var i = 0; i < stamps.length; i++)
                      Tooltip(
                        message: stamps[i].label,
                        child: _StampDown(
                          delay: Duration(milliseconds: 160 + i * 130),
                          child: Transform.translate(
                            offset: Offset(stamps[i].dx, stamps[i].dy),
                            child: Opacity(
                              opacity: stamps[i].upcoming ? .55 : .92,
                              child: Stamp(label: '${stamps[i].label} · ', center: stamps[i].code, color: stamps[i].color,
                                  angle: stamps[i].angle, size: 88),
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              if (stamps.any((s) => s.upcoming))
                Padding(
                  padding: const EdgeInsets.only(top: 14),
                  child: Text(L('Faded stamps are trips still to come.', 'الأختام الباهتة رحلات لسه جاية.'),
                      textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: context.faint)),
                ),
            ]),
          ),
        ]),
      );
}

/// Lands like a rubber stamp: comes down big and blurry-light, hits the page, settles with a small bounce.
class _StampDown extends StatefulWidget {
  const _StampDown({required this.child, required this.delay});
  final Widget child;
  final Duration delay;
  @override
  State<_StampDown> createState() => _StampDownState();
}

class _StampDownState extends State<_StampDown> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 460));
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer(widget.delay, () {
      if (!mounted) return;
      _c.forward();
      Timer(const Duration(milliseconds: 300), () {
        if (mounted) HapticFeedback.selectionClick();
      });
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) {
          final t = _c.value;
          final double scale;
          if (t < .65) {
            scale = 2.1 - 1.18 * Curves.easeIn.transform(t / .65); // 2.1 -> .92
          } else {
            scale = .92 + .08 * Curves.easeOutBack.transform((t - .65) / .35);
          }
          return Opacity(
            opacity: (t * 2.2).clamp(0.0, 1.0),
            child: Transform(
              alignment: Alignment.center,
              transform: perspective()
                ..rotateX((1 - t) * .5)
                ..scaleByDouble(scale, scale, 1, 1),
              child: child,
            ),
          );
        },
        child: widget.child,
      );
}

class _TastePage extends StatelessWidget {
  const _TastePage({required this.taste, required this.interests, required this.onEdit});
  final List<Map> taste;
  final List<String> interests;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    // What the model learned first (with its score), then the interests picked by hand that it hasn't seen yet.
    final items = <(String, int?)>[
      for (final x in taste.take(8)) ('${x['interest']}', (x['score'] as num?)?.round()),
      for (final i in interests)
        if (!taste.any((x) => x['interest'] == i)) (i, null),
    ];
    return _Page(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(child: Text(tr('taste'), style: display(size: 17, color: context.ink))),
          SizedBox(
            height: 44,
            child: TextButton.icon(onPressed: onEdit, icon: const Icon(Icons.edit_note_rounded, size: 20), label: Text(L('Edit', 'تعديل'))),
          ),
        ]),
        const SizedBox(height: 8),
        if (items.isEmpty)
          Text(L('Pick what you love - suggestions will follow your taste.', 'اختار اللي بتحبه - والاقتراحات هتمشي على ذوقك.'),
              style: TextStyle(color: context.muted))
        else
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (var i = 0; i < items.length; i++)
              Reveal(
                delay: Duration(milliseconds: 40 * i),
                offset: 12,
                child: _TasteChip(interest: items[i].$1, score: items[i].$2),
              ),
          ]),
      ]),
    );
  }
}

class _TasteChip extends StatelessWidget {
  const _TasteChip({required this.interest, this.score});
  final String interest;
  final int? score;
  @override
  Widget build(BuildContext context) {
    final c = DC.tag[interest] ?? DC.teal;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 7, 10, 7),
      decoration: BoxDecoration(
        color: c.withValues(alpha: context.dark ? .16 : .13),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: c.withValues(alpha: .45)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Text(DC.emoji[interest] ?? '•', style: const TextStyle(fontSize: 15)),
        const SizedBox(width: 6),
        Text(tr('int.$interest'), style: TextStyle(fontWeight: FontWeight.w700, color: context.ink, fontSize: 13)),
        if (score != null) ...[
          const SizedBox(width: 6),
          Text('$score', style: mono(size: 12, color: c)),
        ],
      ]),
    );
  }
}

/// A link drawn as a small horizontal ticket (the stub holds the count or an arrow).
class _LinkPass extends StatelessWidget {
  const _LinkPass({required this.emoji, required this.title, required this.subtitle, required this.color, required this.onTap, this.count});
  final String emoji, title, subtitle;
  final Color color;
  final VoidCallback onTap;
  final int? count;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: Ticket(
          axis: Axis.horizontal,
          elevation: 6,
          notch: 10,
          gap: 16,
          main: Padding(
            padding: const EdgeInsetsDirectional.fromSTEB(14, 14, 8, 14),
            child: Row(children: [
              Container(
                width: 44,
                height: 44,
                alignment: Alignment.center,
                decoration: BoxDecoration(color: color.withValues(alpha: .16), borderRadius: BorderRadius.circular(14)),
                child: Text(emoji, style: const TextStyle(fontSize: 22)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                  Text(title, style: display(size: 16, color: context.ink)),
                  Text(subtitle, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 12.5)),
                ]),
              ),
            ]),
          ),
          stub: SizedBox(
            width: 58,
            child: Center(
              child: count != null && count! > 0
                  ? Text('$count', style: mono(size: 20, color: color))
                  : Icon(Icons.chevron_right, color: color),
            ),
          ),
        ),
      );
}

// ---------------------------------------------------------------- sign in / create account
String? passwordProblem(String p) {
  if (p.length < 8) return tr('ePassLen');
  if (!RegExp(r'[A-Za-z؀-ۿ]').hasMatch(p) || !RegExp(r'\d').hasMatch(p)) return tr('ePassMix');
  return null;
}

String authError(ApiException e) {
  if (e.status == 0) return tr('errNet');
  if (e.status == 429) return tr('eMany');
  if (e.status == 409) return tr('eExists');
  if (e.status == 401) return tr('eWrong');
  if (e.field == 'email') return tr('eEmail');
  if (e.field == 'name') return tr('eName');
  if (e.field == 'password' || e.field == 'new') return e.message.contains('Mix') ? tr('ePassMix') : tr('ePassLen');
  return e.message;
}

Future<void> showAuthSheet(BuildContext context, AppState st, {bool signUp = false}) => showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _AuthSheet(state: st, signUp: signUp),
    );

class _AuthSheet extends StatefulWidget {
  const _AuthSheet({required this.state, required this.signUp});
  final AppState state;
  final bool signUp;
  @override
  State<_AuthSheet> createState() => _AuthSheetState();
}

class _AuthSheetState extends State<_AuthSheet> {
  late bool up = widget.signUp;
  final name = TextEditingController(), email = TextEditingController(), pass = TextEditingController();
  bool busy = false, show = false;
  String? err, eName, eEmail, ePass;

  @override
  void dispose() {
    name.dispose();
    email.dispose();
    pass.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      err = null;
      eName = up && name.text.trim().isEmpty ? tr('eName') : null;
      eEmail = RegExp(r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$', caseSensitive: false).hasMatch(email.text.trim()) ? null : tr('eEmail');
      ePass = up ? passwordProblem(pass.text) : (pass.text.isEmpty ? tr('ePassLen') : null);
    });
    if (eName != null || eEmail != null || ePass != null) {
      HapticFeedback.heavyImpact();
      return;
    }
    setState(() => busy = true);
    try {
      await widget.state.auth(signUp: up, name: name.text.trim(), email: email.text.trim(), password: pass.text);
      if (!mounted) return;
      final first = (widget.state.user!['name'] as String).split(' ').first;
      Navigator.pop(context);
      toast(context, tr(up ? 'welcome' : 'welcomeBack', [first]));
    } on ApiException catch (e) {
      setState(() => err = authError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom + MediaQuery.viewPaddingOf(context).bottom),
        child: SingleChildScrollView(
          child: AutofillGroup(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(L('PASSPORT CONTROL', 'الجوازات'),
                        style: TextStyle(fontSize: 11, letterSpacing: 1.6, fontWeight: FontWeight.w800, color: context.faint)),
                    AnimatedSwitcher(
                      duration: const Duration(milliseconds: 250),
                      child: Text(up ? tr('signUp') : tr('signIn'), key: ValueKey(up), style: display(size: 26, color: context.ink)),
                    ),
                  ]),
                ),
                Stamp(label: up ? 'NEW TRAVELLER · ' : 'WELCOME BACK · ', center: '✈', color: up ? DC.teal : DC.violet, size: 62, angle: .2),
              ]),
              const SizedBox(height: 16),
              _Segments<bool>(
                value: up,
                expand: true,
                options: [(false, tr('signIn')), (true, tr('signUp'))],
                onChanged: (v) => setState(() {
                  up = v;
                  err = null;
                }),
              ),
              const SizedBox(height: 16),
              AnimatedSize(
                duration: const Duration(milliseconds: 250),
                curve: Curves.easeOutCubic,
                child: up
                    ? Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: TextField(controller: name, textInputAction: TextInputAction.next, autofillHints: const [AutofillHints.name],
                            decoration: InputDecoration(labelText: tr('name'), errorText: eName, prefixIcon: const Icon(Icons.person_outline))),
                      )
                    : const SizedBox(width: double.infinity),
              ),
              TextField(controller: email, keyboardType: TextInputType.emailAddress, textInputAction: TextInputAction.next,
                  textDirection: TextDirection.ltr, autofillHints: const [AutofillHints.email],
                  decoration: InputDecoration(labelText: tr('email'), errorText: eEmail, prefixIcon: const Icon(Icons.alternate_email))),
              const SizedBox(height: 12),
              TextField(
                controller: pass, obscureText: !show, textDirection: TextDirection.ltr, onSubmitted: (_) => _submit(),
                autofillHints: [up ? AutofillHints.newPassword : AutofillHints.password],
                decoration: InputDecoration(
                  labelText: tr('password'), errorText: ePass, helperText: up ? tr('passHint') : null,
                  prefixIcon: const Icon(Icons.lock_outline),
                  suffixIcon: IconButton(onPressed: () => setState(() => show = !show),
                      icon: Icon(show ? Icons.visibility_off_outlined : Icons.visibility_outlined)),
                ),
              ),
              if (err != null) _ErrorBox(err!),
              const SizedBox(height: 18),
              BrandButton(label: up ? tr('signUp') : tr('signIn'), busy: busy, onTap: _submit),
            ]),
          ),
        ),
      );
}
