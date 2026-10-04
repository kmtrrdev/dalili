import 'package:flutter/material.dart';

import '../core/api.dart';
import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../widgets/common.dart';
import 'wizard_screen.dart' show currencies, interestKeys;

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key, required this.state});
  final AppState state;
  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Future<Map<String, dynamic>?>? _dash;
  String? _dashFor;

  AppState get st => widget.state;

  Future<Map<String, dynamic>?> _loadDash() async {
    try {
      return await st.api.get('/api/me/dashboard') as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final u = st.user;
    if (u != null && (_dash == null || _dashFor != u['id'])) {
      _dashFor = u['id'] as String;
      _dash = _loadDash();
    }
    return Scaffold(
      appBar: AppBar(title: Text(tr('profile'))),
      body: ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 32), children: [
        if (u == null) _GuestCard(onAuth: (up) => showAuthSheet(context, st, signUp: up)) else ...[
          _UserHeader(user: u),
          const SizedBox(height: 14),
          FutureBuilder<Map<String, dynamic>?>(
            future: _dash,
            builder: (_, s) => _Stats(stats: (s.data?['stats'] as Map<String, dynamic>?)),
          ),
          if (((st.recs?['taste'] as List?) ?? []).isNotEmpty) ...[
            const SizedBox(height: 14),
            _TasteCard(taste: (st.recs!['taste'] as List).cast<Map<String, dynamic>>()),
          ],
        ],
        _groupTitle(tr('settings')),
        Card(
          child: Column(children: [
            ListTile(
              leading: const Icon(Icons.translate_rounded),
              title: Text(tr('language')),
              trailing: SegmentedButton<String>(
                showSelectedIcon: false,
                segments: const [ButtonSegment(value: 'ar', label: Text('عربي')), ButtonSegment(value: 'en', label: Text('EN'))],
                selected: {st.lang},
                onSelectionChanged: (v) => st.setLang(v.first),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.dark_mode_outlined),
              title: Text(tr('theme')),
              trailing: DropdownButton<ThemeMode>(
                value: st.themeMode,
                underline: const SizedBox(),
                items: [
                  DropdownMenuItem(value: ThemeMode.system, child: Text(tr('themeSystem'))),
                  DropdownMenuItem(value: ThemeMode.light, child: Text(tr('themeLight'))),
                  DropdownMenuItem(value: ThemeMode.dark, child: Text(tr('themeDark'))),
                ],
                onChanged: (m) => st.setTheme(m ?? ThemeMode.system),
              ),
            ),
            if (u != null) ...[
              ListTile(
                leading: const Icon(Icons.flight_takeoff_rounded),
                title: Text(tr('homeCity')),
                subtitle: Text((u['prefs']?['home_city'] as String?)?.isNotEmpty == true ? u['prefs']['home_city'] as String : '—'),
                onTap: () => _editText(tr('homeCity'), u['prefs']?['home_city'] as String? ?? '', (v) => st.updateProfile({'home_city': v})),
              ),
              ListTile(
                leading: const Icon(Icons.payments_outlined),
                title: Text(tr('currency')),
                trailing: DropdownButton<String>(
                  value: (u['prefs']?['currency'] as String?) ?? 'USD',
                  underline: const SizedBox(),
                  items: [for (final c in currencies) DropdownMenuItem(value: c, child: Text(c))],
                  onChanged: (c) => st.updateProfile({'currency': c}),
                ),
              ),
              ListTile(
                leading: const Icon(Icons.favorite_border_rounded),
                title: Text(tr('interests')),
                subtitle: Text(((u['prefs']?['interests'] as List?) ?? []).map((i) => '${DC.emoji[i]} ${tr('int.$i')}').join('  ')),
                onTap: _editInterests,
              ),
            ],
            ListTile(
              leading: const Icon(Icons.dns_outlined),
              title: Text(tr('server')),
              subtitle: Text(st.baseUrl, textDirection: TextDirection.ltr),
              onTap: _editServer,
            ),
          ]),
        ),
        if (u != null) ...[
          _groupTitle(tr('profile')),
          Card(
            child: Column(children: [
              ListTile(leading: const Icon(Icons.lock_outline_rounded), title: Text(tr('changePassword')), onTap: _changePassword),
              ListTile(
                leading: const Icon(Icons.logout_rounded),
                title: Text(tr('signOut')),
                onTap: () async {
                  await st.signOut();
                  if (context.mounted) toast(context, tr('signedOut'));
                },
              ),
              ListTile(
                leading: const Icon(Icons.delete_forever_rounded, color: DC.rose),
                title: Text(tr('deleteAccount'), style: const TextStyle(color: DC.rose, fontWeight: FontWeight.w700)),
                onTap: _deleteAccount,
              ),
            ]),
          ),
        ],
        _groupTitle(tr('about')),
        Card(
          child: ListTile(
            leading: const Text('🧠', style: TextStyle(fontSize: 24)),
            title: Text(tr('appName')),
            subtitle: Text(tr('howItWorks')),
          ),
        ),
      ]),
    );
  }

  Widget _groupTitle(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 22, 4, 8),
        child: Text(t.toUpperCase(), style: TextStyle(color: context.muted, fontWeight: FontWeight.w800, fontSize: 12, letterSpacing: .8)),
      );

  Future<void> _editText(String title, String value, Future<void> Function(String) save) async {
    final c = TextEditingController(text: value);
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(title),
        content: TextField(controller: c, autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: Text(tr('cancel'))),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: Text(tr('save'))),
        ],
      ),
    );
    if (ok == true) {
      await save(c.text.trim());
      if (mounted) toast(context, tr('saved'));
    }
  }

  Future<void> _editInterests() async {
    final picked = {...((st.user?['prefs']?['interests'] as List?) ?? []).cast<String>()};
    final ok = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (s) => StatefulBuilder(
        builder: (s, set) => Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('interests'), style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 14),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final k in interestKeys)
                FilterChip(
                  label: Text('${DC.emoji[k]} ${tr('int.$k')}'),
                  selected: picked.contains(k),
                  onSelected: (v) => set(() => v ? picked.add(k) : picked.remove(k)),
                ),
            ]),
            const SizedBox(height: 18),
            BrandButton(label: tr('save'), onTap: () => Navigator.pop(s, true)),
          ]),
        ),
      ),
    );
    if (ok == true) {
      await st.updateProfile({'interests': picked.toList()});
      if (mounted) toast(context, tr('saved'));
    }
  }

  Future<void> _editServer() async {
    final c = TextEditingController(text: st.baseUrl);
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text(tr('server')),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr('serverSub'), style: TextStyle(color: context.muted, fontSize: 13)),
          const SizedBox(height: 12),
          TextField(controller: c, keyboardType: TextInputType.url, textDirection: TextDirection.ltr),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: Text(tr('cancel'))),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: Text(tr('save'))),
        ],
      ),
    );
    if (ok == true) {
      final reachable = await st.setBaseUrl(c.text);
      if (!mounted) return;
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
    await showDialog<void>(
      context: context,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => AlertDialog(
          title: Text(tr('changePassword')),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: cur, obscureText: true, decoration: InputDecoration(labelText: tr('current'))),
            const SizedBox(height: 10),
            TextField(controller: next, obscureText: true, decoration: InputDecoration(labelText: tr('newPass'), helperText: tr('passHint'))),
            if (err != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(err!, style: const TextStyle(color: DC.rose))),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d), child: Text(tr('cancel'))),
            FilledButton(
              onPressed: () async {
                final p = passwordProblem(next.text);
                if (p != null) return set(() => err = p);
                try {
                  await st.changePassword(cur.text, next.text);
                  if (d.mounted) Navigator.pop(d);
                  if (mounted) toast(context, tr('passChanged'));
                } on ApiException catch (e) {
                  set(() => err = authError(e));
                }
              },
              child: Text(tr('save')),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _deleteAccount() async {
    final pw = TextEditingController();
    String? err;
    await showDialog<void>(
      context: context,
      builder: (d) => StatefulBuilder(
        builder: (d, set) => AlertDialog(
          title: Text(tr('deleteAccount')),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(tr('deleteAccountSub')),
            const SizedBox(height: 12),
            TextField(controller: pw, obscureText: true, decoration: InputDecoration(labelText: tr('password'))),
            if (err != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(err!, style: const TextStyle(color: DC.rose))),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d), child: Text(tr('cancel'))),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: DC.rose, foregroundColor: Colors.white),
              onPressed: () async {
                try {
                  await st.deleteAccount(pw.text);
                  if (d.mounted) Navigator.pop(d);
                } on ApiException catch (e) {
                  set(() => err = authError(e));
                }
              },
              child: Text(tr('delete')),
            ),
          ],
        ),
      ),
    );
  }
}

class _GuestCard extends StatelessWidget {
  const _GuestCard({required this.onAuth});
  final void Function(bool signUp) onAuth;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(gradient: context.dark ? DC.aurora
            : const LinearGradient(colors: [Color(0xFFCFF5F0), Color(0xFFDCE4FF)]), borderRadius: BorderRadius.circular(24)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('🧳✨', style: TextStyle(fontSize: 34)),
          const SizedBox(height: 8),
          Text(tr('guestTitle'), style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 6),
          Text(tr('guestSub'), style: TextStyle(color: context.dark ? const Color(0xFFB9C6E0) : const Color(0xFF33425D), height: 1.4)),
          const SizedBox(height: 18),
          BrandButton(label: tr('signUp'), icon: Icons.person_add_alt_1_rounded, onTap: () => onAuth(true)),
          const SizedBox(height: 10),
          SizedBox(width: double.infinity, child: OutlinedButton(onPressed: () => onAuth(false), child: Text(tr('signIn')))),
        ]),
      );
}

class _UserHeader extends StatelessWidget {
  const _UserHeader({required this.user});
  final Map<String, dynamic> user;
  @override
  Widget build(BuildContext context) {
    final name = user['name'] as String;
    final since = DateTime.tryParse(user['created_at'] as String? ?? '');
    return Row(children: [
      Container(
        width: 64, height: 64, alignment: Alignment.center,
        decoration: const BoxDecoration(shape: BoxShape.circle, gradient: SweepGradient(colors: [DC.teal, DC.violet, DC.amber, DC.teal])),
        child: Text(name.trim().characters.first.toUpperCase(),
            style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900, color: Color(0xFF06101C))),
      ),
      const SizedBox(width: 14),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(name, style: Theme.of(context).textTheme.headlineMedium),
          Text(user['email'] as String, style: TextStyle(color: context.muted), textDirection: TextDirection.ltr),
          if (since != null)
            Text(tr('memberSince', ['${since.month}/${since.year}']), style: TextStyle(color: context.faint, fontSize: 12)),
        ]),
      ),
    ]);
  }
}

class _Stats extends StatelessWidget {
  const _Stats({required this.stats});
  final Map<String, dynamic>? stats;
  @override
  Widget build(BuildContext context) {
    final s = stats ?? {};
    Widget tile(String emoji, Object? v, String k) => Expanded(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
              child: Column(children: [
                Text(emoji, style: const TextStyle(fontSize: 18)),
                Text('${v ?? '–'}', style: Theme.of(context).textTheme.titleLarge),
                Text(tr(k), textAlign: TextAlign.center, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: context.muted, fontSize: 11)),
              ]),
            ),
          ),
        );
    return Row(children: [
      tile('🧳', s['planned'], 'stTrips'), const SizedBox(width: 8),
      tile('🌍', s['countries'], 'stCountries'), const SizedBox(width: 8),
      tile('📅', s['days'], 'stDays'), const SizedBox(width: 8),
      tile('⭐', s['avg_score'], 'stScore'),
    ]);
  }
}

class _TasteCard extends StatelessWidget {
  const _TasteCard({required this.taste});
  final List<Map<String, dynamic>> taste;
  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('taste'), style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            for (final x in taste.take(6))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Row(children: [
                  SizedBox(width: 120, child: Text('${DC.emoji[x['interest']]} ${tr('int.${x['interest']}')}', style: const TextStyle(fontSize: 13))),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: LinearProgressIndicator(value: (x['score'] as num) / 100, minHeight: 9,
                          backgroundColor: context.line, color: DC.tag[x['interest']]),
                    ),
                  ),
                  SizedBox(width: 34, child: Text('${x['score']}', textAlign: TextAlign.end, style: const TextStyle(fontWeight: FontWeight.w800))),
                ]),
              ),
          ]),
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

  Future<void> _submit() async {
    setState(() {
      err = null;
      eName = up && name.text.trim().isEmpty ? tr('eName') : null;
      eEmail = RegExp(r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$', caseSensitive: false).hasMatch(email.text.trim()) ? null : tr('eEmail');
      ePass = up ? passwordProblem(pass.text) : (pass.text.isEmpty ? tr('ePassLen') : null);
    });
    if (eName != null || eEmail != null || ePass != null) return;
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
        padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.of(context).viewInsets.bottom),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text(up ? tr('signUp') : tr('signIn'), style: Theme.of(context).textTheme.headlineMedium, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            SegmentedButton<bool>(
              showSelectedIcon: false,
              segments: [ButtonSegment(value: false, label: Text(tr('signIn'))), ButtonSegment(value: true, label: Text(tr('signUp')))],
              selected: {up},
              onSelectionChanged: (v) => setState(() { up = v.first; err = null; }),
            ),
            const SizedBox(height: 16),
            if (up) ...[
              TextField(controller: name, textInputAction: TextInputAction.next, autofillHints: const [AutofillHints.name],
                  decoration: InputDecoration(labelText: tr('name'), errorText: eName, prefixIcon: const Icon(Icons.person_outline))),
              const SizedBox(height: 12),
            ],
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
            if (err != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: DC.rose.withValues(alpha: .12), borderRadius: BorderRadius.circular(12)),
                child: Text(err!, style: const TextStyle(color: DC.rose, fontWeight: FontWeight.w700)),
              ),
            ],
            const SizedBox(height: 18),
            BrandButton(label: up ? tr('signUp') : tr('signIn'), busy: busy, onTap: _submit),
          ]),
        ),
      );
}
