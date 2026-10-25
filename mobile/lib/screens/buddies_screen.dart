import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:shared_preferences/shared_preferences.dart';

import '../core/api.dart';
import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';

// ---------------------------------------------------------------- pure helpers (tested in buddies_helpers_test.dart)

/// "Mona H." -> "MH". An Arabic name gives its first letter only (two joined letters would read as a word).
String buddyInitials(String? name) {
  final words = (name ?? '').replaceAll('.', ' ').trim().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
  if (words.isEmpty) return '?';
  final first = words.first.characters.first;
  if (words.length < 2 || RegExp(r'[؀-ۿ]').hasMatch(first)) return first.toUpperCase();
  return (first + words[1].characters.first).toUpperCase();
}

int? _idOf(Object? m) => m is Map && m['id'] is num ? (m['id'] as num).toInt() : null;

/// The messages we have plus the ones the server just sent: one per id, oldest first; messages still being sent
/// (no id yet) stay at the end. Local flags (reported, the bubble's key) survive the server's copy.
List<Map<String, dynamic>> mergeBuddyMessages(List<Map<String, dynamic>> have, Iterable<dynamic> incoming) {
  final byId = <int, Map<String, dynamic>>{};
  final pending = <Map<String, dynamic>>[];
  for (final m in have) {
    final id = _idOf(m);
    if (id == null) {
      pending.add(m);
    } else {
      byId[id] = m;
    }
  }
  for (final raw in incoming) {
    final id = _idOf(raw);
    if (id == null) continue;
    byId[id] = {...?byId[id], ...Map<String, dynamic>.from(raw as Map)};
  }
  final ids = byId.keys.toList()..sort();
  return [for (final id in ids) byId[id]!, ...pending];
}

/// The messages hidden since we showed them (by moderation or reports): ones we know in the re-read window
/// (after < id <= upTo) that the server no longer sends.
Set<int> hiddenBuddyIds({required Iterable<int> known, required Iterable<int> returned, required int after, required int upTo}) {
  final back = returned.toSet();
  return {for (final id in known) if (id > after && id <= upTo && !back.contains(id)) id};
}

/// True when this city's dates are behind us (the server refuses to join it).
bool stopIsOver(String? endIso, DateTime now) {
  final end = DateTime.tryParse(endIso ?? '');
  return end != null && end.isBefore(DateTime(now.year, now.month, now.day));
}

/// What a system message is: someone 'left', or Dalili's 'welcome' (both start with a wave), else a 'note'.
String buddySystemKind(String text) {
  if (RegExp(r'left the group\.?$').hasMatch(text.trim())) return 'left';
  return text.trimLeft().startsWith('👋') ? 'welcome' : 'note';
}

/// A member's colour: the same name always gets the same one.
Color buddyColor(String key) {
  const palette = [DC.teal, DC.violet, DC.amber, DC.rose, DC.sky, DC.green, DC.coral];
  final h = key.codeUnits.fold<int>(11, (h, c) => (h * 31 + c) & 0x7fffffff);
  return palette[h % palette.length];
}

/// The direction of a message from its first letter (members write in either language).
TextDirection _dirOf(String s, TextDirection fallback) {
  final m = RegExp(r'[A-Za-z؀-ۿ]').firstMatch(s);
  if (m == null) return fallback;
  return RegExp(r'[؀-ۿ]').hasMatch(m.group(0)!) ? TextDirection.rtl : TextDirection.ltr;
}

String _interest(String i) => DC.emoji.containsKey(i) ? '${DC.emoji[i]} ${tr('int.$i')}' : i;

String _fastText() => L("You're sending messages very fast - wait a moment.", 'بتبعت رسايل بسرعة قوي - استنى لحظة.');

String _errText(Object e, {bool load = false}) {
  if (e is ApiException) {
    if (e.status == 0) return tr('errNet');
    if (e.status == 429) return _fastText();
    if (e.status == 401) return L('Sign in to meet your travel buddies.', 'سجّل دخولك عشان تقابل رفقاء سفرك.');
    if (e.status == 403) return L("You're not in this group anymore.", 'انت مش في الجروب ده دلوقتي.');
    if (!isArabic && e.status == 400 && !e.message.startsWith('HTTP')) return e.message;
  }
  return load
      ? L("Couldn't load your travel buddies - try again.", 'معرفتش أحمّل رفقاء السفر - جرّب تاني.')
      : L("That didn't work - try again.", 'محصلش - جرّب تاني.');
}

String _rules() => L(
    'Only your first name and initial, your dates in this city and your interests are shown - never your hotel or '
        'flights. Dalili may suggest meeting at a sight that is in two members\' plans. Meet in public places, keep '
        'personal details to yourself, and report anything that feels wrong.',
    'بيظهر اسمك الأول وأول حرف من اسم العيلة بس، ومواعيدك في المدينة دي، واهتماماتك - عمره ما بيظهر فندقك أو طيرانك. '
        'دليلي ممكن يقترح تتقابلوا عند مكان موجود في برنامج اتنين منكم. اتقابلوا في أماكن عامة، خلّي بياناتك الشخصية '
        'لنفسك، وبلّغ عن أي حاجة مش مريحة.');

String _seenKey(String gid) => 'buddySeen.$gid';

/// Remembers the last message read in a group (the groups list shows a dot when there are newer ones).
Future<void> _markSeen(String gid, int id) async {
  try {
    final p = await SharedPreferences.getInstance();
    if ((p.getInt(_seenKey(gid)) ?? 0) < id) await p.setInt(_seenKey(gid), id);
  } catch (_) {}
}

// ---------------------------------------------------------------- the board: a trip's cities, or all my groups

/// Travel buddies. With [tripId]: the trip's cities as gate passes - who else is there at the same time, and a Join
/// button per city. Without (opened from the Passport): the traveller's groups. Tapping one opens its chat.
class BuddiesScreen extends StatefulWidget {
  const BuddiesScreen({super.key, required this.state, this.tripId});
  final AppState state;
  final String? tripId;

  @override
  State<BuddiesScreen> createState() => _BuddiesScreenState();
}

class _BuddiesScreenState extends State<BuddiesScreen> {
  bool _loading = true;
  Object? _error;
  bool _signedIn = false;
  List<Map<String, dynamic>> _cities = [];
  List<Map<String, dynamic>> _groups = [];
  Map<String, int> _seen = {};
  final Set<int> _women = {}; // the stops whose women-only switch is on
  int? _joining;

  bool get _tripMode => widget.tripId != null;
  Api get _api => widget.state.api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// [quiet]: the passes stay on screen while they refresh (coming back from a chat, pull to refresh).
  Future<void> _load({bool quiet = false}) async {
    setState(() {
      _loading = !quiet;
      _error = null;
    });
    try {
      if (_tripMode) {
        final r = await _api.get('/api/buddies/preview', query: {'trip_id': widget.tripId!}) as Map<String, dynamic>;
        _signedIn = r['signed_in'] == true;
        _cities = [for (final c in (r['cities'] as List? ?? const [])) Map<String, dynamic>.from(c as Map)];
      } else if (widget.state.user == null) {
        _signedIn = false;
      } else {
        final r = await _api.get('/api/buddies/groups') as List;
        _groups = [for (final g in r) Map<String, dynamic>.from(g as Map)];
        _signedIn = true;
        try {
          final p = await SharedPreferences.getInstance();
          _seen = {for (final g in _groups) g['id'] as String: p.getInt(_seenKey(g['id'] as String)) ?? 0};
        } catch (_) {}
      }
    } catch (e) {
      if (e is ApiException && e.status == 401) {
        _signedIn = false;
      } else {
        _error = e;
      }
    }
    if (mounted) setState(() => _loading = false);
  }

  /// Sign-in lives on the Passport tab, under every pushed screen.
  void _signIn() {
    Navigator.of(context).popUntil((r) => r.isFirst);
    widget.state.goTab(Tabs.me);
  }

  Future<void> _open(String gid) async {
    await Navigator.of(context).push(passRoute(BuddyChatScreen(state: widget.state, groupId: gid)));
    if (mounted) _load(quiet: true); // joined, left or read something: the board changes
  }

  Future<void> _join(Map<String, dynamic> c) async {
    final stop = (c['stop'] as num).toInt();
    setState(() => _joining = stop);
    try {
      final r = await _api.post('/api/buddies/join',
          {'trip_id': widget.tripId, 'stop': stop, 'women_only': _women.contains(stop)}) as Map<String, dynamic>;
      HapticFeedback.mediumImpact();
      if (!mounted) return;
      if (r['created'] == true) {
        toast(context, L('A new group for ${c['city']} - the travellers who come next will join you.',
            'جروب جديد لـ${c['city']} - اللي جايين بعدك هينضموا ليك.'));
      }
      await _open(r['group_id'] as String);
    } catch (e) {
      if (!mounted) return;
      if (e is ApiException && e.status == 401) {
        setState(() => _signedIn = false);
      }
      toast(context, _errText(e), action: e is ApiException && e.status == 401 ? tr('signIn') : null, onAction: _signIn);
    } finally {
      if (mounted) setState(() => _joining = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.dark ? DC.night : DC.day,
      extendBodyBehindAppBar: true,
      appBar: AppBar(title: Text(L('Travel buddies', 'رفقاء السفر'))),
      body: SkyBackground(
        planes: 2,
        glow: DC.violet,
        child: SafeArea(bottom: false, child: _body(context)),
      ),
    );
  }

  Widget _body(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator(color: DC.teal));
    if (_error != null) {
      return Center(
        child: SingleChildScrollView(
          child: EmptyState(emoji: '📡', title: _errText(_error!, load: true), action: L('Try again', 'جرّب تاني'), onAction: _load),
        ),
      );
    }
    final bottom = MediaQuery.paddingOf(context).bottom + 28;
    final children = <Widget>[
      Reveal(child: _Hero(tripMode: _tripMode)),
      const SizedBox(height: 18),
    ];
    if (_tripMode) {
      if (!_signedIn) children.add(Reveal(delay: const Duration(milliseconds: 60), child: _SignInCard(onSignIn: _signIn)));
      if (_cities.isEmpty) {
        children.add(EmptyState(emoji: '🧭', title: L('No cities in this trip yet', 'لسه مفيش مدن في الرحلة دي'),
            subtitle: L('Plan the trip first - then meet who else is going.', 'خطط الرحلة الأول - وبعدين اتعرّف على اللي رايحين.')));
      }
      for (var i = 0; i < _cities.length; i++) {
        final c = _cities[i];
        final stop = (c['stop'] as num?)?.toInt() ?? i;
        children.add(Padding(
          padding: const EdgeInsets.only(bottom: 18),
          child: Reveal(
            delay: Duration(milliseconds: 90 + i * 80),
            child: _GateTicket(
              city: c,
              index: i,
              signedIn: _signedIn,
              womenOnly: _women.contains(stop),
              joining: _joining == stop,
              onWomen: (v) => setState(() => v ? _women.add(stop) : _women.remove(stop)),
              onJoin: _joining == null ? () => _join(c) : null,
              onOpen: () => _open(c['group_id'] as String),
              onSignIn: _signIn,
            ),
          ),
        ));
      }
    } else if (!_signedIn) {
      children.add(_SignInCard(onSignIn: _signIn));
    } else if (_groups.isEmpty) {
      children.add(EmptyState(emoji: '👥', title: L('No groups yet', 'لسه مفيش جروبات'),
          subtitle: L('Open a trip and tap Travel buddies to meet people in the same city at the same time.',
              'افتح رحلة ودوس على رفقاء السفر عشان تتعرّف على ناس في نفس المدينة في نفس الوقت.')));
    } else {
      for (var i = 0; i < _groups.length; i++) {
        final g = _groups[i];
        final last = (g['last_message'] as num?)?.toInt() ?? 0;
        children.add(Padding(
          padding: const EdgeInsets.only(bottom: 14),
          child: Reveal(
            delay: Duration(milliseconds: 60 + i * 70),
            child: _GroupTicket(group: g, unread: last > (_seen[g['id']] ?? 0), onTap: () => _open(g['id'] as String)),
          ),
        ));
      }
    }
    children.add(const SizedBox(height: 6));
    children.add(_RulesCard(text: _rules()));
    return RefreshIndicator(
      color: DC.teal,
      onRefresh: () => _load(quiet: true),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
        padding: EdgeInsets.fromLTRB(16, 8, 16, bottom),
        children: children,
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.tripMode});
  final bool tripMode;

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: AlignmentDirectional.centerStart,
          child: SplitFlap(
            isArabic ? 'رفقاء السفر' : 'TRAVEL BUDDIES',
            style: isArabic ? display(size: 30, color: context.ink) : mono(size: 20, color: Colors.white, weight: FontWeight.w800),
          ),
        ),
        const SizedBox(height: 10),
        Text(
          tripMode
              ? L("Travelling without friends this time? Meet people who'll be in the same city at the same time - a small "
                  'group chat, matched by your dates and interests.',
                  'مسافر لوحدك المرة دي؟ اتعرّف على ناس هتكون في نفس المدينة في نفس الوقت - جروب صغير، على حسب مواعيدك واهتماماتك.')
              : L('Your groups: the travellers in the same city at the same time as you.',
                  'جروباتك: المسافرين اللي في نفس مدينتك في نفس الوقت.'),
          style: TextStyle(color: context.muted, fontSize: 14.5, height: 1.45),
        ),
      ]);
}

class _SignInCard extends StatelessWidget {
  const _SignInCard({required this.onSignIn});
  final VoidCallback onSignIn;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 18),
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: context.card.withValues(alpha: .92),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: DC.amber.withValues(alpha: .45)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Text('🔐', style: TextStyle(fontSize: 26)),
            const SizedBox(width: 12),
            Expanded(
              child: Text(L('Sign in to meet your travel buddies', 'سجّل دخولك عشان تقابل رفقاء سفرك'),
                  style: display(size: 17, color: context.ink)),
            ),
          ]),
          const SizedBox(height: 8),
          Text(
            L('Groups are for travellers with an account, so everyone in them is a real person. You can still see who '
                'is going.', 'الجروبات للمسافرين اللي عندهم حساب، عشان كل اللي فيها ناس حقيقية. تقدر برضه تشوف مين رايح.'),
            style: TextStyle(color: context.muted, height: 1.4),
          ),
          const SizedBox(height: 14),
          BrandButton(label: tr('signIn'), icon: Icons.lock_outline_rounded, onTap: onSignIn),
        ]),
      );
}

class _RulesCard extends StatelessWidget {
  const _RulesCard({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: context.card.withValues(alpha: .7),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: context.line),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('🛡️', style: TextStyle(fontSize: 20)),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: TextStyle(color: context.muted, fontSize: 13, height: 1.45))),
        ]),
      );
}

/// One city of the trip as a gate pass: the dates, who else is there, what you share, and the way in.
class _GateTicket extends StatelessWidget {
  const _GateTicket({
    required this.city,
    required this.index,
    required this.signedIn,
    required this.womenOnly,
    required this.joining,
    required this.onWomen,
    required this.onJoin,
    required this.onOpen,
    required this.onSignIn,
  });
  final Map<String, dynamic> city;
  final int index;
  final bool signedIn, womenOnly, joining;
  final ValueChanged<bool> onWomen;
  final VoidCallback? onJoin;
  final VoidCallback onOpen, onSignIn;

  @override
  Widget build(BuildContext context) {
    final n = (city['travellers'] as num?)?.toInt() ?? 0;
    final women = (city['women_only'] as num?)?.toInt() ?? 0;
    final shared = [for (final s in (city['shared_interests'] as List? ?? const [])) '$s'];
    final joined = city['group_id'] as String?;
    final over = joined == null && stopIsOver(city['end'] as String?, DateTime.now());
    final accent = joined != null ? DC.green : (over ? context.faint : (n > 0 ? DC.amber : DC.teal));
    final status = joined != null
        ? Pill(L('Joined', 'منضم'), color: DC.green, icon: Icons.check_circle_rounded)
        : over
            ? Pill(L('Departed', 'خلصت'), color: context.faint)
            : n > 0
                ? Pill(L('Boarding', 'بيركبوا'), color: DC.amber)
                : Pill(L('Gate open', 'البوابة مفتوحة'), color: DC.teal);
    final people = n == 0
        ? L("No one yet - join and you'll meet the travellers who come next.", 'لسه مفيش حد - ادخل وهتتعرّف على اللي جايين بعدك.')
        : n == 1
            ? L('1 traveller there around your dates', 'مسافر واحد هناك في نفس مواعيدك')
            : L('$n travellers there around your dates', '$n مسافرين هناك في نفس مواعيدك');

    final main = Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          PassField(L('Gate', 'بوابة'), 'B${(index + 1).toString().padLeft(2, '0')}', valueColor: accent),
          const Spacer(),
          status,
        ]),
        const SizedBox(height: 10),
        Text(city['city'] as String? ?? '', maxLines: 2, overflow: TextOverflow.ellipsis,
            style: display(size: 28, color: context.ink, height: 1.1)),
        const SizedBox(height: 12),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: PassField(L('From', 'من'), fmtDate(city['start'] as String?))),
          Expanded(child: PassField(L('To', 'لحد'), fmtDate(city['end'] as String?, year: true))),
          PassField(L('Travellers', 'مسافرين'), '$n', end: true, big: true, valueColor: accent),
        ]),
        const SizedBox(height: 12),
        Text(people, style: TextStyle(color: context.muted, fontSize: 13.5, height: 1.35)),
        if (shared.isNotEmpty || women > 0) ...[
          const SizedBox(height: 10),
          Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            if (shared.isNotEmpty)
              Text('${L('You share', 'مشتركين في')}:', style: TextStyle(color: context.faint, fontSize: 12, fontWeight: FontWeight.w700)),
            for (final s in shared) Pill(_interest(s), color: DC.tag[s] ?? DC.violet),
            if (women > 0) Pill('👭 ${L('$women in women-only groups', '$women في جروبات للسيدات بس')}', color: DC.rose),
          ]),
        ],
      ]),
    );

    Widget stub;
    if (joined != null) {
      stub = SizedBox(
        width: double.infinity,
        child: FilledButton.icon(
          onPressed: onOpen,
          icon: const Icon(Icons.chat_bubble_rounded, size: 18),
          label: Text(L('Open the chat', 'افتح الشات')),
        ),
      );
    } else if (over) {
      stub = Text(L('This part of the trip is over.', 'الجزء ده من الرحلة خلص.'), style: TextStyle(color: context.faint));
    } else if (!signedIn) {
      stub = SizedBox(
        width: double.infinity,
        child: OutlinedButton.icon(
          onPressed: onSignIn,
          icon: const Icon(Icons.lock_outline_rounded, size: 18),
          label: Text(L('Sign in to join', 'سجّل دخول عشان تنضم')),
        ),
      );
    } else {
      stub = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => onWomen(!womenOnly),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 48),
              child: Row(children: [
                const Text('👭', style: TextStyle(fontSize: 18)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(L('Women-only group (self-declared)', 'جروب للسيدات بس (بإقرارك)'),
                      style: TextStyle(color: context.ink, fontWeight: FontWeight.w600, fontSize: 13.5)),
                ),
                Switch(value: womenOnly, onChanged: onWomen, activeThumbColor: DC.rose),
              ]),
            ),
          ),
        ),
        const SizedBox(height: 8),
        BrandButton(label: L('Join the group', 'ادخل الجروب'), icon: Icons.person_add_alt_1_rounded, busy: joining, onTap: onJoin),
      ]);
    }

    return Tilt3D(
      maxAngle: .07,
      child: Ticket(
        main: main,
        stub: Padding(padding: const EdgeInsets.fromLTRB(18, 10, 18, 16), child: stub),
      ),
    );
  }
}

/// A group in the traveller's list: a small concert-style ticket, a dot when there are messages they haven't read.
class _GroupTicket extends StatelessWidget {
  const _GroupTicket({required this.group, required this.unread, required this.onTap});
  final Map<String, dynamic> group;
  final bool unread;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final n = (group['members'] as num?)?.toInt() ?? 0;
    final color = buddyColor(group['city'] as String? ?? '');
    return Pressable(
      onTap: onTap,
      child: Ticket(
        axis: Axis.horizontal,
        main: Padding(
          padding: const EdgeInsetsDirectional.fromSTEB(18, 14, 12, 14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text('BUDDY PASS', style: mono(size: 10, color: color, spacing: 2)),
            const SizedBox(height: 4),
            Text(group['city'] as String? ?? '', maxLines: 1, overflow: TextOverflow.ellipsis,
                style: display(size: 22, color: context.ink)),
            const SizedBox(height: 2),
            Text('${fmtDate(group['start'] as String?)} – ${fmtDate(group['end'] as String?, year: true)}',
                style: TextStyle(color: context.muted, fontSize: 13)),
            const SizedBox(height: 8),
            Wrap(spacing: 6, runSpacing: 6, children: [
              Pill(n == 1 ? L('1 traveller', 'مسافر واحد') : L('$n travellers', '$n مسافرين'), color: color),
              if (group['women_only'] == true) Pill('👭 ${L('Women only', 'للسيدات بس')}', color: DC.rose),
              if (unread) Pill(L('New messages', 'رسايل جديدة'), color: DC.amber, solid: true),
            ]),
          ]),
        ),
        stub: SizedBox(
          width: 78,
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Stack(clipBehavior: Clip.none, children: [
              const Text('💬', style: TextStyle(fontSize: 26)),
              if (unread)
                PositionedDirectional(
                  top: -2,
                  end: -4,
                  child: Container(width: 11, height: 11,
                      decoration: BoxDecoration(color: DC.amber, shape: BoxShape.circle, border: Border.all(color: context.ticket, width: 2))),
                ),
            ]),
            const SizedBox(height: 6),
            Text(L('OPEN', 'افتح'), style: isArabic ? display(size: 12, color: context.muted) : mono(size: 11, color: context.muted, spacing: 1.5)),
          ]),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- the group chat

/// One group's chat: the pass (city, dates, who's in), ideas to meet, the messages (polled every 3 s while the
/// screen is on show), a composer, and report / block / leave.
class BuddyChatScreen extends StatefulWidget {
  const BuddyChatScreen({super.key, required this.state, required this.groupId});
  final AppState state;
  final String groupId;

  @override
  State<BuddyChatScreen> createState() => _BuddyChatScreenState();
}

class _BuddyChatScreenState extends State<BuddyChatScreen> with WidgetsBindingObserver {
  static const _pollEvery = Duration(seconds: 3);
  static const _window = 40; // how many recent messages a re-read checks

  final _scroll = ScrollController();
  final _field = TextEditingController();
  final _focus = FocusNode();

  Map<String, dynamic>? _group;
  List<Map<String, dynamic>> _members = [];
  List<String> _ideas = [];
  List<Map<String, dynamic>> _msgs = [];
  int _after = 0; // the newest id the server has sent us: polls ask for what came after it
  bool _loading = true;
  Object? _error;
  int? _goneStatus; // set when we're no longer allowed in (left elsewhere, signed out)

  Timer? _timer;
  bool _inFlight = false;
  int _ticks = 0;
  bool _appActive = true;
  ValueListenable<TickerModeData>? _onstage;

  int _unseen = 0; // messages that arrived while scrolled up
  String? _notice;
  Timer? _noticeTimer;
  int _seq = 0;
  bool _hasText = false;

  Api get _api => widget.state.api;
  String get _path => '/api/buddies/groups/${Uri.encodeComponent(widget.groupId)}';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _field.addListener(() {
      final has = _field.text.trim().isNotEmpty;
      if (has != _hasText) setState(() => _hasText = has);
    });
    _scroll.addListener(() {
      if (_unseen > 0 && _scroll.hasClients && _scroll.offset < 40) setState(() => _unseen = 0);
    });
    _load();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Off when another full screen covers this one (its route goes offstage); dialogs and sheets keep it on.
    final n = TickerMode.getValuesNotifier(context);
    if (n != _onstage) {
      _onstage?.removeListener(_visibility);
      _onstage = n..addListener(_visibility);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState s) {
    _appActive = s == AppLifecycleState.resumed;
    _visibility();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _onstage?.removeListener(_visibility);
    _timer?.cancel();
    _noticeTimer?.cancel();
    _scroll.dispose();
    _field.dispose();
    _focus.dispose();
    super.dispose();
  }

  // ---------------------------------------------------------------- polling
  bool get _visible => mounted && _appActive && (_onstage?.value.enabled ?? true) && _goneStatus == null && _group != null;

  void _visibility() {
    if (!_visible) {
      _timer?.cancel();
      _timer = null;
    } else if (_timer == null && !_inFlight) {
      _schedule(Duration.zero); // back on show: catch up at once
    }
  }

  void _schedule([Duration d = _pollEvery]) {
    _timer?.cancel();
    _timer = _visible ? Timer(d, _poll) : null;
  }

  void _pollSoon() {
    if (!_inFlight) _schedule(const Duration(milliseconds: 250));
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final d = await _api.get(_path) as Map<String, dynamic>;
      if (!mounted) return;
      _apply(d, first: true);
      setState(() => _loading = false);
      _schedule();
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e;
          _loading = false;
        });
      }
    }
  }

  Future<void> _poll() async {
    _timer = null;
    if (!_visible || _inFlight) return;
    _inFlight = true;
    _ticks++;
    // Every tenth poll re-reads the recent messages too: the ones moderation or reports hid since drop out.
    final known = [for (final m in _msgs) ?_idOf(m)];
    final resync = _ticks % 10 == 0 && known.isNotEmpty;
    final after = resync ? math.max(0, known[math.max(0, known.length - _window)] - 1) : _after;
    try {
      final d = await _api.get(_path, query: {'after': '$after'}) as Map<String, dynamic>;
      if (mounted) _apply(d, resyncFrom: resync ? after : null);
    } on ApiException catch (e) {
      if (mounted && (e.status == 401 || e.status == 403 || e.status == 404)) setState(() => _goneStatus = e.status);
    } catch (_) {
      // a missed poll: the next one catches up
    } finally {
      _inFlight = false;
      if (mounted) _schedule();
    }
  }

  void _apply(Map<String, dynamic> d, {bool first = false, int? resyncFrom}) {
    final incoming = (d['messages'] as List?) ?? const [];
    final ids = [for (final m in incoming) ?_idOf(m)];
    final before = {for (final m in _msgs) ?_idOf(m)};
    var next = mergeBuddyMessages(_msgs, incoming);

    // A message of ours the poll brought before its send call returned: it replaces the "sending" bubble in place.
    for (final m in next) {
      final id = _idOf(m);
      if (id == null || before.contains(id) || m['mine'] != true) continue;
      final i = next.indexWhere((t) => _idOf(t) == null && t['sending'] == true && t['text'] == m['text']);
      if (i >= 0) {
        m['_key'] = next[i]['_key'];
        m['_shown'] = true;
        next.removeAt(i);
      }
    }

    if (resyncFrom != null) {
      final upTo = incoming.length >= 200 && ids.isNotEmpty ? ids.reduce(math.max) : 1 << 52;
      final gone = hiddenBuddyIds(known: [for (final m in next) ?_idOf(m)], returned: ids, after: resyncFrom, upTo: upTo);
      if (gone.isNotEmpty) {
        next = [
          for (final m in next)
            if (!gone.contains(_idOf(m)))
              m
            else if (m['mine'] == true)
              {...m, 'kind': 'hidden'}, // ours: say so, instead of it vanishing
        ];
      }
    }

    var freshOthers = 0;
    for (final m in next) {
      final id = _idOf(m);
      if (first || id == null || before.contains(id) || m['_shown'] == true) continue;
      m['_fresh'] = true;
      if (m['mine'] != true) freshOthers++;
    }
    final newest = ids.isEmpty ? _after : math.max(_after, ids.reduce(math.max));
    final members = [for (final x in (d['members'] as List?) ?? const []) Map<String, dynamic>.from(x as Map)];
    final ideas = [for (final x in (d['ideas'] as List?) ?? const []) '$x'];

    setState(() {
      _group = {'city': d['city'], 'start': d['start'], 'end': d['end'], 'women_only': d['women_only'] == true};
      if (members.isNotEmpty) _members = members;
      if (first || ideas.isNotEmpty) _ideas = ideas; // later polls don't carry the ideas
      _msgs = next;
      _after = newest;
    });
    if (newest > 0) _markSeen(widget.groupId, newest);
    if (freshOthers > 0) {
      HapticFeedback.selectionClick();
      if (_scroll.hasClients && _scroll.offset > 120) {
        setState(() => _unseen += freshOthers);
      } else {
        _toBottom();
      }
    }
  }

  // ---------------------------------------------------------------- actions
  void _toBottom() {
    if (_unseen > 0) setState(() => _unseen = 0);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients && _scroll.offset > 0) {
        _scroll.animateTo(0, duration: const Duration(milliseconds: 360), curve: Curves.easeOutCubic);
      }
    });
  }

  void _flash(String text) {
    _noticeTimer?.cancel();
    setState(() => _notice = text);
    _noticeTimer = Timer(const Duration(seconds: 6), () {
      if (mounted) setState(() => _notice = null);
    });
  }

  Map<String, dynamic>? get _me {
    for (final m in _members) {
      if (m['you'] == true) return m;
    }
    return null;
  }

  Future<void> _send({Map<String, dynamic>? retry}) async {
    final text = (retry?['text'] as String? ?? _field.text).trim();
    if (text.isEmpty) return;
    final temp = <String, dynamic>{
      '_key': 'tmp${++_seq}', '_fresh': true, 'kind': 'user', 'mine': true, 'sending': true, 'text': text,
      'name': _me?['name'], 'at': DateTime.now().toUtc().toIso8601String(),
    };
    setState(() {
      if (retry != null) _msgs.remove(retry);
      _msgs = [..._msgs, temp];
      if (retry == null) _field.clear();
    });
    HapticFeedback.lightImpact();
    _toBottom();
    try {
      final r = await _api.post('$_path/messages', {'text': text}) as Map<String, dynamic>;
      final id = (r['id'] as num).toInt();
      if (!mounted) return;
      setState(() {
        final had = _msgs.contains(temp);
        _msgs = [for (final m in _msgs) if (!identical(m, temp)) m];
        if (had && !_msgs.any((m) => _idOf(m) == id)) {
          _msgs = mergeBuddyMessages(_msgs, [
            {'id': id, 'user': _me?['id'], 'name': _me?['name'], 'kind': 'user', 'text': text, 'at': temp['at'], 'mine': true},
          ]);
          final real = _msgs.firstWhere((m) => _idOf(m) == id);
          real['_key'] = temp['_key'];
        }
      });
      _pollSoon();
    } catch (e) {
      if (!mounted) return;
      if (e is ApiException && e.status == 429) {
        // Too fast: the words go back in the box, to send in a moment.
        setState(() {
          _msgs = [for (final m in _msgs) if (!identical(m, temp)) m];
          if (_field.text.trim().isEmpty) _field.text = text;
        });
        HapticFeedback.heavyImpact();
        _flash(_fastText());
      } else if (e is ApiException && (e.status == 401 || e.status == 403)) {
        setState(() {
          _msgs = [for (final m in _msgs) if (!identical(m, temp)) m];
          _goneStatus = e.status;
        });
      } else {
        setState(() {
          temp['sending'] = false;
          temp['failed'] = true;
        });
      }
    }
  }

  void _discard(Map<String, dynamic> m) => setState(() => _msgs = [for (final x in _msgs) if (!identical(x, m)) x]);

  Future<void> _actions(Map<String, dynamic> m) async {
    HapticFeedback.mediumImpact();
    final mine = m['mine'] == true;
    final name = m['name'] as String? ?? '';
    final act = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 10),
            child: Text(m['text'] as String? ?? '', maxLines: 3, overflow: TextOverflow.ellipsis,
                textDirection: _dirOf(m['text'] as String? ?? '', Directionality.of(ctx)),
                style: TextStyle(color: ctx.muted, height: 1.4)),
          ),
          if (m['failed'] == true) ...[
            _SheetAction(emoji: '↻', label: L('Send again', 'ابعت تاني'), value: 'retry'),
            _SheetAction(emoji: '✕', label: L('Discard', 'امسحها'), value: 'discard'),
          ],
          _SheetAction(emoji: '📋', label: L('Copy text', 'انسخ الكلام'), value: 'copy'),
          if (!mine && _idOf(m) != null) ...[
            if (m['reported'] != true) _SheetAction(emoji: '🚩', label: L('Report message', 'بلّغ عن الرسالة'), value: 'report'),
            _SheetAction(emoji: '⛔', label: L('Block $name', 'احظر $name'), value: 'block', danger: true),
          ],
          const SizedBox(height: 8),
        ]),
      ),
    );
    if (!mounted || act == null) return;
    switch (act) {
      case 'copy':
        await Clipboard.setData(ClipboardData(text: m['text'] as String? ?? ''));
        if (mounted) toast(context, L('Copied', 'اتنسخ'));
      case 'retry':
        _send(retry: m);
      case 'discard':
        _discard(m);
      case 'report':
        _report(m);
      case 'block':
        _block(m);
    }
  }

  Future<void> _report(Map<String, dynamic> m) async {
    final reason = await showDialog<String>(context: context, builder: (_) => const _ReportDialog());
    if (reason == null || !mounted) return;
    try {
      final r = await _api.post('/api/buddies/messages/${_idOf(m)}/report', {'reason': reason}) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        if (r['hidden'] == true) {
          _msgs = [for (final x in _msgs) if (!identical(x, m)) x];
        } else {
          m['reported'] = true;
        }
      });
      toast(context, L("Thanks - we'll look at it.", 'شكراً - هنراجعها.'));
    } catch (e) {
      if (mounted) toast(context, _errText(e));
    }
  }

  Future<void> _block(Map<String, dynamic> m) async {
    final name = m['name'] as String? ?? '';
    final user = m['user'] as String?;
    if (user == null) return;
    final ok = await _confirm(
      title: L('Block $name?', 'تحظر $name؟'),
      body: L("You won't see their messages in any group. They aren't told.", 'مش هتشوف رسايله في أي جروب. ومش هيتقاله.'),
      action: L('Block', 'احظر'),
    );
    if (!ok || !mounted) return;
    try {
      await _api.post('/api/buddies/block', {'user_id': user});
      if (!mounted) return;
      HapticFeedback.mediumImpact();
      setState(() => _msgs = [for (final x in _msgs) if (x['user'] != user) x]);
      toast(context, L("Blocked. You won't see their messages.", 'اتحظر. مش هتشوف رسايله.'));
    } catch (e) {
      if (mounted) toast(context, _errText(e));
    }
  }

  Future<void> _leave() async {
    final ok = await _confirm(
      title: L('Leave this group?', 'تخرج من الجروب ده؟'),
      body: L('The group will be told you left. You can join this city again from your trip.',
          'الجروب هيعرف إنك خرجت. تقدر تدخل المدينة دي تاني من رحلتك.'),
      action: L('Leave', 'اخرج'),
    );
    if (!ok || !mounted) return;
    try {
      await _api.post('$_path/leave');
      if (!mounted) return;
      _timer?.cancel();
      toast(context, L('You left the group.', 'خرجت من الجروب.'));
      Navigator.of(context).pop();
    } catch (e) {
      if (mounted) toast(context, _errText(e));
    }
  }

  Future<bool> _confirm({required String title, required String body, required String action}) async =>
      await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('cancel'))),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: DC.rose, foregroundColor: Colors.white, minimumSize: const Size(48, 44)),
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(action),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> _more() async {
    final act = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _SheetAction(emoji: '👥', label: L('Who is in the group', 'مين في الجروب'), value: 'members'),
          _SheetAction(emoji: '🛡️', label: L('Safety and privacy', 'الأمان والخصوصية'), value: 'rules'),
          _SheetAction(emoji: '👋', label: L('Leave the group', 'اخرج من الجروب'), value: 'leave', danger: true),
          const SizedBox(height: 8),
        ]),
      ),
    );
    if (!mounted) return;
    if (act == 'members') _showMembers();
    if (act == 'rules') {
      showModalBottomSheet<void>(
        context: context,
        builder: (ctx) => SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(L('Safety and privacy', 'الأمان والخصوصية'), style: Theme.of(ctx).textTheme.titleLarge),
              const SizedBox(height: 10),
              Text(_rules(), style: TextStyle(color: ctx.muted, height: 1.5)),
              const SizedBox(height: 10),
              Text(L('Long-press a message to report it or block its sender.', 'دوس مطوّل على أي رسالة عشان تبلّغ عنها أو تحظر صاحبها.'),
                  style: TextStyle(color: ctx.ink, fontWeight: FontWeight.w600)),
            ]),
          ),
        ),
      );
    }
    if (act == 'leave') _leave();
  }

  void _showMembers() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * .75),
        child: SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
            children: [
              Text(L('Who is in the group', 'مين في الجروب'), style: Theme.of(ctx).textTheme.titleLarge),
              const SizedBox(height: 4),
              Text(L('First name and initial only.', 'الاسم الأول وأول حرف بس.'), style: TextStyle(color: ctx.muted, fontSize: 13)),
              const SizedBox(height: 12),
              for (final m in _members) _MemberRow(member: m),
            ],
          ),
        ),
      ),
    );
  }

  void _useIdea(String idea) {
    final clean = idea.replaceFirst(RegExp(r'^\S*[^\w\s؀-ۿ]\s*'), '');
    _field.text = clean.isEmpty ? idea : clean;
    _field.selection = TextSelection.collapsed(offset: _field.text.length);
    _focus.requestFocus();
  }

  // ---------------------------------------------------------------- build
  @override
  Widget build(BuildContext context) {
    final g = _group;
    final members = _members.length;
    return Scaffold(
      backgroundColor: context.dark ? DC.night : DC.day,
      extendBodyBehindAppBar: true,
      resizeToAvoidBottomInset: true,
      appBar: AppBar(
        titleSpacing: 0,
        title: MediaQuery.withClampedTextScaling(
          maxScaleFactor: 1.25,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(g?['city'] as String? ?? L('Travel buddies', 'رفقاء السفر'), maxLines: 1, overflow: TextOverflow.ellipsis),
            if (g != null)
              Text(
                '${members == 1 ? L('1 traveller', 'مسافر واحد') : L('$members travellers', '$members مسافرين')}'
                ' · ${fmtDate(g['start'] as String?)} – ${fmtDate(g['end'] as String?)}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 12, color: context.muted, fontWeight: FontWeight.w500),
              ),
          ]),
        ),
        actions: [
          if (_members.isNotEmpty)
            Semantics(
              button: true,
              label: L('Who is in the group', 'مين في الجروب'),
              child: Pressable(
                onTap: _showMembers,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 10),
                  child: _Avatars(members: _members, size: 28, max: 3),
                ),
              ),
            ),
          if (g != null)
            IconButton(
              tooltip: L('More', 'المزيد'),
              onPressed: _more,
              icon: Text('⋯', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900, color: context.ink, height: 1)),
            ),
          const SizedBox(width: 4),
        ],
      ),
      body: SkyBackground(
        planes: 2,
        glow: DC.violet,
        child: SafeArea(bottom: false, child: _chatBody(context)),
      ),
    );
  }

  Widget _chatBody(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator(color: DC.teal));
    if (_error != null) {
      final e = _error!;
      final out = e is ApiException && (e.status == 401 || e.status == 403 || e.status == 404);
      return Center(
        child: SingleChildScrollView(
          child: EmptyState(
            emoji: out ? '🔒' : '📡',
            title: _errText(e, load: true),
            action: out ? null : L('Try again', 'جرّب تاني'),
            onAction: out ? null : _load,
          ),
        ),
      );
    }
    return Column(children: [
      Expanded(
        child: Stack(children: [
          Positioned.fill(child: _list(context)),
          PositionedDirectional(
            bottom: 10,
            start: 0,
            end: 0,
            child: Center(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 220),
                transitionBuilder: (c, a) => ScaleTransition(scale: a, child: FadeTransition(opacity: a, child: c)),
                child: _unseen == 0
                    ? const SizedBox.shrink()
                    : Pressable(
                        key: const ValueKey('unseen'),
                        onTap: _toBottom,
                        child: Container(
                          constraints: const BoxConstraints(minHeight: 44),
                          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                          decoration: BoxDecoration(gradient: DC.brand, borderRadius: BorderRadius.circular(999),
                              boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: .25), blurRadius: 14, offset: const Offset(0, 6))]),
                          child: Text(
                            '↓  ${_unseen == 1 ? L('1 new message', 'رسالة جديدة') : L('$_unseen new messages', '$_unseen رسايل جديدة')}',
                            style: const TextStyle(color: DC.onBrand, fontWeight: FontWeight.w800),
                          ),
                        ),
                      ),
              ),
            ),
          ),
        ]),
      ),
      AnimatedSize(
        duration: const Duration(milliseconds: 240),
        curve: Curves.easeOutCubic,
        child: _notice == null
            ? const SizedBox(width: double.infinity)
            : Container(
                width: double.infinity,
                margin: const EdgeInsets.fromLTRB(12, 0, 12, 6),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: DC.amber.withValues(alpha: context.dark ? .16 : .2),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: DC.amber.withValues(alpha: .5)),
                ),
                child: Text('⏳  $_notice', style: TextStyle(color: context.ink, fontWeight: FontWeight.w600, fontSize: 13)),
              ),
      ),
      _goneStatus != null ? _goneBar(context) : _composer(context),
    ]);
  }

  Widget _list(BuildContext context) {
    // Oldest first: the pass, the ideas, the safety line, then the messages with a chip where the day changes.
    final entries = <Widget Function()>[
      () => Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Reveal(child: _PassHeader(groupId: widget.groupId, group: _group!, members: _members, onMembers: _showMembers)),
          ),
      if (_ideas.isNotEmpty)
        () => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Reveal(delay: const Duration(milliseconds: 120), child: _IdeasStrip(ideas: _ideas, onUse: _useIdea)),
            ),
      () => Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Text(
              '🛡️ ${L('Meet in public places · long-press a message to report or block', 'اتقابلوا في أماكن عامة · دوس مطوّل على أي رسالة عشان تبلّغ أو تحظر')}',
              textAlign: TextAlign.center,
              style: TextStyle(color: context.faint, fontSize: 12),
            ),
          ),
      if (_msgs.isEmpty)
        () => Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Text(L("Say hello 👋 - you're the first here.", 'قول أهلاً 👋 - انت أول واحد هنا.'),
                  textAlign: TextAlign.center, style: TextStyle(color: context.muted, fontSize: 15)),
            ),
    ];
    DateTime? prevDay;
    Map<String, dynamic>? prev;
    for (final m in _msgs) {
      final at = DateTime.tryParse(m['at'] as String? ?? '')?.toLocal();
      final day = at == null ? prevDay : DateTime(at.year, at.month, at.day);
      if (day != null && day != prevDay) {
        entries.add(() => _DayChip(day: day));
        prev = null;
      }
      prevDay = day;
      final cont = prev != null && prev['kind'] == 'user' && m['kind'] == 'user' && prev['user'] == m['user'] && prev['mine'] == m['mine'];
      prev = m;
      final fresh = m.remove('_fresh') == true; // plays once: a rebuilt bubble keeps its state
      entries.add(() => _Arrive(
            key: ValueKey(m['_key'] ?? 'id${_idOf(m)}'),
            animate: fresh,
            mine: m['mine'] == true,
            child: _MessageView(
              m: m,
              cont: cont,
              onLongPress: m['kind'] == 'user' && m['sending'] != true ? () => _actions(m) : null,
              onRetry: m['failed'] == true ? () => _send(retry: m) : null,
            ),
          ));
    }
    return ListView.builder(
      controller: _scroll,
      reverse: true, // the newest message sits at the bottom, by the composer
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
      padding: const EdgeInsets.fromLTRB(14, 8, 14, 12),
      itemCount: entries.length,
      itemBuilder: (_, i) => entries[entries.length - 1 - i](),
    );
  }

  Widget _composer(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: context.card.withValues(alpha: .94),
          border: Border(top: BorderSide(color: context.line)),
        ),
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Expanded(
                child: TextField(
                  controller: _field,
                  focusNode: _focus,
                  minLines: 1,
                  maxLines: 5,
                  maxLength: 1000,
                  keyboardType: TextInputType.multiline,
                  textCapitalization: TextCapitalization.sentences,
                  buildCounter: (_, {required currentLength, required isFocused, maxLength}) => currentLength > 850
                      ? Text('$currentLength/1000', style: TextStyle(fontSize: 11, color: currentLength >= 1000 ? DC.rose : context.faint))
                      : null,
                  decoration: InputDecoration(
                    hintText: L('Write to the group…', 'اكتب للجروب…'),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Semantics(
                  button: true,
                  label: L('Send', 'ابعت'),
                  child: Pressable(
                    onTap: _hasText ? () => _send() : null,
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 200),
                      width: 48,
                      height: 48,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: _hasText ? DC.brand : null,
                        color: _hasText ? null : context.card2,
                        boxShadow: _hasText ? [BoxShadow(color: DC.teal.withValues(alpha: .35), blurRadius: 14, offset: const Offset(0, 4))] : null,
                      ),
                      child: Icon(Icons.send_rounded, size: 21, color: _hasText ? DC.onBrand : context.faint),
                    ),
                  ),
                ),
              ),
            ]),
          ),
        ),
      );

  Widget _goneBar(BuildContext context) => Container(
        width: double.infinity,
        decoration: BoxDecoration(color: context.card.withValues(alpha: .94), border: Border(top: BorderSide(color: context.line))),
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
            child: Row(children: [
              Expanded(child: Text(_errText(ApiException(_goneStatus!, '')), style: TextStyle(color: context.muted))),
              const SizedBox(width: 8),
              if (_goneStatus == 401)
                FilledButton(
                  onPressed: () {
                    Navigator.of(context).popUntil((r) => r.isFirst);
                    widget.state.goTab(Tabs.me);
                  },
                  child: Text(tr('signIn')),
                )
              else
                OutlinedButton(onPressed: () => Navigator.of(context).pop(), child: Text(L('Back', 'رجوع'))),
            ]),
          ),
        ),
      );
}

/// The group's own pass at the top of the chat: the city on a departures board, the dates, the seats taken, and
/// who's in (tap for everyone).
class _PassHeader extends StatelessWidget {
  const _PassHeader({required this.groupId, required this.group, required this.members, required this.onMembers});
  final String groupId;
  final Map<String, dynamic> group;
  final List<Map<String, dynamic>> members;
  final VoidCallback onMembers;

  @override
  Widget build(BuildContext context) {
    final city = group['city'] as String? ?? '';
    final names = members.map((m) => m['you'] == true ? L('you', 'انت') : '${m['name']}').join(isArabic ? '، ' : ', ');
    return Tilt3D(
      maxAngle: .1,
      child: Ticket(
        main: Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('✦ BUDDY PASS', style: mono(size: 10.5, color: DC.teal, spacing: 2)),
              const Spacer(),
              if (group['women_only'] == true) Pill('👭 ${L('Women only', 'للسيدات بس')}', color: DC.rose),
            ]),
            const SizedBox(height: 10),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: AlignmentDirectional.centerStart,
              child: SplitFlap(
                RegExp(r'[؀-ۿ]').hasMatch(city) ? city : city.toUpperCase(),
                style: RegExp(r'[؀-ۿ]').hasMatch(city)
                    ? display(size: 30, color: context.ink)
                    : mono(size: 24, color: Colors.white, weight: FontWeight.w800),
              ),
            ),
            const SizedBox(height: 14),
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: PassField(L('From', 'من'), fmtDate(group['start'] as String?))),
              Expanded(child: PassField(L('To', 'لحد'), fmtDate(group['end'] as String?, year: true))),
              PassField(L('Seats', 'الأماكن'), '${members.length}/12', end: true),
            ]),
          ]),
        ),
        stub: Padding(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 14),
          child: Column(children: [
            Semantics(
              button: true,
              label: L('Who is in the group', 'مين في الجروب'),
              child: Pressable(
                onTap: onMembers,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 44),
                  child: Row(children: [
                    _Avatars(members: members, size: 34, max: 5),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(names, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: context.muted, fontSize: 13)),
                    ),
                    Text(L('All', 'الكل'), style: const TextStyle(color: DC.teal, fontWeight: FontWeight.w800)),
                  ]),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Barcode(groupId, height: 26),
          ]),
        ),
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.name, required this.size, this.ring});
  final String name;
  final double size;
  final Color? ring;

  @override
  Widget build(BuildContext context) {
    final c = buddyColor(name);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(colors: [c, Color.lerp(c, Colors.black, .35)!], begin: Alignment.topLeft, end: Alignment.bottomRight),
        border: Border.all(color: ring ?? context.ticket, width: 2),
      ),
      child: Text(buddyInitials(name),
          textScaler: TextScaler.noScaling, // it has to fit its circle
          style: TextStyle(color: Colors.white, fontSize: size * .36, fontWeight: FontWeight.w800, height: 1)),
    );
  }
}

/// Overlapping initials circles, "+3" when there are more.
class _Avatars extends StatelessWidget {
  const _Avatars({required this.members, this.size = 30, this.max = 4});
  final List<Map<String, dynamic>> members;
  final double size;
  final int max;

  @override
  Widget build(BuildContext context) {
    final shown = members.take(max).toList();
    final extra = members.length - shown.length;
    final count = shown.length + (extra > 0 ? 1 : 0);
    if (count == 0) return const SizedBox.shrink();
    final step = size * .64;
    return SizedBox(
      width: size + step * (count - 1),
      height: size,
      child: Stack(children: [
        for (var i = 0; i < shown.length; i++)
          PositionedDirectional(start: step * i, child: _Avatar(name: '${shown[i]['name']}', size: size)),
        if (extra > 0)
          PositionedDirectional(
            start: step * shown.length,
            child: Container(
              width: size,
              height: size,
              alignment: Alignment.center,
              decoration: BoxDecoration(shape: BoxShape.circle, color: context.card2, border: Border.all(color: context.ticket, width: 2)),
              child: Text('+$extra', textScaler: TextScaler.noScaling,
                  style: TextStyle(color: context.ink, fontSize: size * .34, fontWeight: FontWeight.w800)),
            ),
          ),
      ]),
    );
  }
}

class _MemberRow extends StatelessWidget {
  const _MemberRow({required this.member});
  final Map<String, dynamic> member;

  @override
  Widget build(BuildContext context) {
    final you = member['you'] == true;
    final days = (member['days_together'] as num?)?.toInt() ?? 0;
    final interests = [for (final i in (member['interests'] as List? ?? const [])) '$i'];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _Avatar(name: '${member['name']}', size: 42, ring: Colors.transparent),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${member['name']}${you ? ' (${L('you', 'انت')})' : ''}', style: display(size: 16, color: context.ink)),
            const SizedBox(height: 2),
            Text(
              '${fmtDate(member['from'] as String?)} – ${fmtDate(member['to'] as String?)}'
              '${you ? '' : ' · ${days == 1 ? L('1 day together', 'يوم مع بعض') : L('$days days together', '$days أيام مع بعض')}'}',
              style: TextStyle(color: context.muted, fontSize: 13),
            ),
            if (interests.isNotEmpty) ...[
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final i in interests) Pill(_interest(i), color: DC.tag[i] ?? DC.violet),
              ]),
            ],
          ]),
        ),
      ]),
    );
  }
}

/// Meet-up ideas from the members' own plans: small cards to swipe through; tapping one drafts it for the group.
class _IdeasStrip extends StatefulWidget {
  const _IdeasStrip({required this.ideas, required this.onUse});
  final List<String> ideas;
  final ValueChanged<String> onUse;

  @override
  State<_IdeasStrip> createState() => _IdeasStripState();
}

class _IdeasStripState extends State<_IdeasStrip> {
  final _pages = PageController(viewportFraction: .88);

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final h = MediaQuery.textScalerOf(context).scale(132).clamp(132.0, 240.0);
    final n = widget.ideas.length;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsetsDirectional.only(start: 4, bottom: 8),
        child: Text('✨ ${L('Ideas to meet', 'أفكار للقاء')}', style: display(size: 16, color: context.ink)),
      ),
      SizedBox(
        height: h,
        child: PageView.builder(
          controller: _pages,
          itemCount: n,
          padEnds: false,
          itemBuilder: (_, i) => Coverflow(
            controller: _pages,
            index: i,
            turn: .3,
            child: Padding(
              padding: const EdgeInsetsDirectional.only(end: 10),
              child: _IdeaCard(text: widget.ideas[i], onUse: () => widget.onUse(widget.ideas[i])),
            ),
          ),
        ),
      ),
      if (n > 1)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: AnimatedBuilder(
            animation: _pages,
            builder: (context, _) {
              final p = _pages.hasClients && _pages.position.haveDimensions ? (_pages.page ?? 0) : 0.0;
              return Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                for (var i = 0; i < n; i++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    width: (p.round() == i) ? 18 : 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: p.round() == i ? DC.amber : context.faint.withValues(alpha: .5),
                      borderRadius: BorderRadius.circular(3),
                    ),
                  ),
              ]);
            },
          ),
        ),
    ]);
  }
}

class _IdeaCard extends StatelessWidget {
  const _IdeaCard({required this.text, required this.onUse});
  final String text;
  final VoidCallback onUse;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onUse,
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            gradient: LinearGradient(
              colors: context.dark
                  ? [const Color(0xFF2A2140), const Color(0xFF13233A)]
                  : [const Color(0xFFFFF4E0), const Color(0xFFF1EEFF)],
              begin: AlignmentDirectional.topStart,
              end: AlignmentDirectional.bottomEnd,
            ),
            border: Border.all(color: DC.amber.withValues(alpha: .35)),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Expanded(
              child: Text(text, maxLines: 4, overflow: TextOverflow.ellipsis,
                  textDirection: _dirOf(text, Directionality.of(context)),
                  style: TextStyle(color: context.ink, fontSize: 14, height: 1.4, fontWeight: FontWeight.w600)),
            ),
            Row(children: [
              const Spacer(),
              Text(L('Suggest to the group', 'اقترحها على الجروب'),
                  style: const TextStyle(color: DC.amber, fontWeight: FontWeight.w800, fontSize: 12.5)),
              const SizedBox(width: 4),
              const Text('→', style: TextStyle(color: DC.amber, fontWeight: FontWeight.w800)),
            ]),
          ]),
        ),
      );
}

class _DayChip extends StatelessWidget {
  const _DayChip({required this.day});
  final DateTime day;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final diff = today.difference(day).inDays;
    final label = diff == 0
        ? L('Today', 'النهارده')
        : diff == 1
            ? L('Yesterday', 'امبارح')
            : DateFormat('EEE d MMM', isArabic ? 'ar' : 'en').format(day);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
          decoration: BoxDecoration(color: context.card.withValues(alpha: .85), borderRadius: BorderRadius.circular(999),
              border: Border.all(color: context.line)),
          child: Text(label, style: TextStyle(color: context.muted, fontSize: 12, fontWeight: FontWeight.w700)),
        ),
      ),
    );
  }
}

/// A new bubble grows in from the composer instead of popping (once; old messages appear as they are).
class _Arrive extends StatefulWidget {
  const _Arrive({super.key, required this.animate, required this.mine, required this.child});
  final bool animate;
  final bool mine;
  final Widget child;

  @override
  State<_Arrive> createState() => _ArriveState();
}

class _ArriveState extends State<_Arrive> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 380), value: widget.animate ? 0 : 1);
  late final Animation<double> _v = CurvedAnimation(parent: _c, curve: Curves.easeOutCubic);

  @override
  void initState() {
    super.initState();
    if (widget.animate) _c.forward();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizeTransition(
        sizeFactor: _v,
        alignment: AlignmentDirectional(widget.mine ? 1 : -1, -1),
        child: FadeTransition(
          opacity: _v,
          child: ScaleTransition(
            scale: Tween(begin: .86, end: 1.0).animate(_v),
            alignment: widget.mine ? AlignmentDirectional.bottomEnd.resolve(Directionality.of(context))
                : AlignmentDirectional.bottomStart.resolve(Directionality.of(context)),
            child: widget.child,
          ),
        ),
      );
}

/// One line of the chat: a member's bubble (ours on the end side), Dalili's welcome as a little pass, a quiet line
/// when someone leaves, or a note where moderation hid one of ours.
class _MessageView extends StatelessWidget {
  const _MessageView({required this.m, required this.cont, this.onLongPress, this.onRetry});
  final Map<String, dynamic> m;
  final bool cont; // the same person's previous line: no name, no avatar
  final VoidCallback? onLongPress;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final text = m['text'] as String? ?? '';
    final dir = Directionality.of(context);
    final kind = m['kind'] as String? ?? 'user';
    if (kind == 'hidden') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Align(
          alignment: AlignmentDirectional.centerEnd,
          child: Text('🛡️ ${L('Your message was hidden by moderation.', 'رسالتك اتخفت من المراجعة.')}',
              style: TextStyle(color: context.faint, fontSize: 12.5, fontStyle: FontStyle.italic)),
        ),
      );
    }
    if (kind == 'system') {
      final sk = buddySystemKind(text);
      if (sk == 'left') {
        final who = RegExp(r'^\W*(.+?) left the group').firstMatch(text)?.group(1);
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Center(
            child: Text(who == null ? text : '👋 ${L('$who left the group', '$who خرج من الجروب')}',
                textAlign: TextAlign.center, style: TextStyle(color: context.faint, fontSize: 12.5)),
          ),
        );
      }
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Container(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(18),
                gradient: LinearGradient(
                  colors: [DC.teal.withValues(alpha: context.dark ? .14 : .16), DC.violet.withValues(alpha: context.dark ? .14 : .12)],
                  begin: AlignmentDirectional.topStart,
                  end: AlignmentDirectional.bottomEnd,
                ),
                border: Border.all(color: DC.teal.withValues(alpha: .35)),
              ),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(
                  width: 30,
                  height: 30,
                  alignment: Alignment.center,
                  decoration: const BoxDecoration(shape: BoxShape.circle, gradient: DC.brand),
                  child: const Icon(Icons.auto_awesome_rounded, size: 16, color: DC.onBrand),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(sk == 'welcome' ? L('DALILI · WELCOME', 'دليلي · ترحيب') : 'DALILI',
                        style: isArabic ? display(size: 11.5, color: DC.teal) : mono(size: 10, color: DC.teal, spacing: 1.5)),
                    const SizedBox(height: 4),
                    Text(text, textDirection: _dirOf(text, dir), style: TextStyle(color: context.ink, height: 1.45, fontSize: 14)),
                  ]),
                ),
              ]),
            ),
          ),
        ),
      );
    }

    final mine = m['mine'] == true;
    final name = m['name'] as String? ?? '';
    final color = buddyColor(name);
    final at = DateTime.tryParse(m['at'] as String? ?? '')?.toLocal();
    final time = at == null ? '' : DateFormat.Hm(isArabic ? 'ar' : 'en').format(at);
    final sending = m['sending'] == true, failed = m['failed'] == true, reported = m['reported'] == true;
    final maxW = math.min(MediaQuery.sizeOf(context).width * .76, 460.0);
    final ink = mine ? DC.onBrand : context.ink;
    const r = Radius.circular(20), tail = Radius.circular(6);
    final bubble = Container(
      constraints: BoxConstraints(maxWidth: maxW),
      padding: const EdgeInsets.fromLTRB(14, 9, 14, 7),
      decoration: BoxDecoration(
        gradient: mine ? DC.brand : null,
        color: mine ? null : context.card.withValues(alpha: .96),
        borderRadius: BorderRadiusDirectional.only(
          topStart: !mine && !cont ? tail : r,
          topEnd: mine && !cont ? tail : r,
          bottomStart: r,
          bottomEnd: r,
        ),
        border: mine ? null : Border.all(color: context.line),
        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: context.dark ? .25 : .08), blurRadius: 10, offset: const Offset(0, 3))],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        if (!mine && !cont)
          Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Text(name, style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12.5)),
          ),
        Text(text, textDirection: _dirOf(text, dir), style: TextStyle(color: ink, fontSize: 15, height: 1.4)),
        const SizedBox(height: 3),
        Row(mainAxisSize: MainAxisSize.min, children: [
          if (reported) Text('🚩 ', style: TextStyle(fontSize: 10.5, color: ink.withValues(alpha: .6))),
          Text(time, style: TextStyle(fontSize: 10.5, color: ink.withValues(alpha: .6))),
          if (mine) ...[
            const SizedBox(width: 4),
            if (sending)
              SizedBox(width: 10, height: 10, child: CircularProgressIndicator(strokeWidth: 1.4, color: ink.withValues(alpha: .7)))
            else if (!failed)
              Icon(Icons.check_circle_rounded, size: 11, color: ink.withValues(alpha: .6)),
          ],
        ]),
      ]),
    );

    final row = Row(
      mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        if (!mine) ...[
          cont ? const SizedBox(width: 32) : _Avatar(name: name, size: 32, ring: Colors.transparent),
          const SizedBox(width: 8),
        ],
        Flexible(
          child: Opacity(opacity: sending ? .75 : 1, child: bubble),
        ),
      ],
    );

    return Padding(
      padding: EdgeInsets.only(top: cont ? 3 : 10),
      child: Column(crossAxisAlignment: mine ? CrossAxisAlignment.end : CrossAxisAlignment.start, children: [
        Pressable(scale: .98, onTap: onRetry, onLongPress: onLongPress, child: row),
        if (failed)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(L("Not sent - tap to try again", 'متبعتتش - دوس عشان تجرّب تاني'),
                style: const TextStyle(color: DC.rose, fontSize: 12, fontWeight: FontWeight.w700)),
          ),
      ]),
    );
  }
}

class _SheetAction extends StatelessWidget {
  const _SheetAction({required this.emoji, required this.label, required this.value, this.danger = false});
  final String emoji;
  final String label;
  final String value;
  final bool danger;

  @override
  Widget build(BuildContext context) => ListTile(
        minTileHeight: 52,
        leading: SizedBox(width: 28, child: Center(child: Text(emoji, style: const TextStyle(fontSize: 20)))),
        title: Text(label, style: TextStyle(fontWeight: FontWeight.w700, color: danger ? DC.rose : context.ink)),
        onTap: () => Navigator.pop(context, value),
      );
}

/// Report a message: pick why, then confirm.
class _ReportDialog extends StatefulWidget {
  const _ReportDialog();

  @override
  State<_ReportDialog> createState() => _ReportDialogState();
}

class _ReportDialogState extends State<_ReportDialog> {
  String? _reason;

  @override
  Widget build(BuildContext context) {
    final reasons = [
      ('harassment', L('Harassment or hate', 'تحرش أو كراهية')),
      ('scam', L('Scam or a suspicious link', 'نصب أو لينك مش مريح')),
      ('spam', L('Spam', 'سبام')),
      ('other', L('Something else', 'حاجة تانية')),
    ];
    return AlertDialog(
      title: Text(L('Report this message?', 'تبلّغ عن الرسالة دي؟')),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(L('Two reports hide a message for everyone. The sender isn\'t told who reported it.',
              'بلاغين بيخفوا الرسالة عن الكل. وصاحبها مش هيعرف مين بلّغ.'), style: TextStyle(color: context.muted, height: 1.4)),
          const SizedBox(height: 14),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final (k, label) in reasons)
              ChoiceChip(
                label: Text(label),
                selected: _reason == k,
                showCheckmark: false,
                materialTapTargetSize: MaterialTapTargetSize.padded,
                onSelected: (_) => setState(() => _reason = k),
              ),
          ]),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('cancel'))),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: DC.rose, foregroundColor: Colors.white, minimumSize: const Size(48, 44)),
          onPressed: _reason == null ? null : () => Navigator.pop(context, _reason),
          child: Text(L('Report', 'بلّغ')),
        ),
      ],
    );
  }
}
