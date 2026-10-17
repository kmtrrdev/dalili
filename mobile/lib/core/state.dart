import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'i18n.dart';

class ChatLine {
  ChatLine(this.role, this.text, {this.tripCard = false});
  final String role; // user | assistant
  final String text;
  final bool tripCard; // an assistant message that comes with a finished plan
}

/// The live progress of one planning turn, shown as a checklist.
class Progress {
  final List<String> steps = [];
  String? current;
  void add(String key) {
    if (!steps.contains(key)) steps.add(key);
    current = key;
  }
}

const _toolSteps = {
  'flights': 'flights', 'hotels': 'hotels', 'places': 'places', 'activities': 'activities', 'transport': 'transport',
  'weather': 'weather', 'currency': 'currency', 'knowledge': 'knowledge',
};
const _nodeSteps = {'understand': 'understand', 'plan': 'plan', 'critic': 'review'};

/// Everything the app knows: settings, the signed-in user, the open trip and its conversation.
class AppState extends ChangeNotifier {
  late SharedPreferences _prefs;
  final _secure = const FlutterSecureStorage();
  late Api api;

  String lang = 'ar';
  ThemeMode themeMode = ThemeMode.system;
  String baseUrl = defaultBaseUrl;
  Map<String, dynamic>? user;
  bool ready = false;

  // the open trip + chat
  String? tripId;
  Map<String, dynamic>? trip;
  final List<ChatLine> messages = [];
  bool busy = false;
  Progress? progress;
  int tab = 0;

  // home data
  Map<String, dynamic>? recs;
  List<dynamic> trips = [];

  /// Set when building an APK to share: flutter build apk --dart-define=DALILI_SERVER=https://...
  static const _builtInServer = String.fromEnvironment('DALILI_SERVER');

  static String get defaultBaseUrl {
    if (_builtInServer.isNotEmpty) return _builtInServer;
    // Android emulator: the computer is 10.0.2.2. iOS simulator / desktop: localhost.
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) return 'http://10.0.2.2:8001';
    return 'http://127.0.0.1:8001';
  }

  bool get signedIn => user != null;
  Map<String, dynamic>? get plan {
    final plans = trip?['plans'] as Map<String, dynamic>?;
    if (plans == null || plans.isEmpty) return null;
    return plans[trip!['selected_mode']] as Map<String, dynamic>?;
  }

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    lang = _prefs.getString('lang') ?? (PlatformDispatcher.instance.locale.languageCode == 'ar' ? 'ar' : 'en');
    currentLang = lang;
    themeMode = ThemeMode.values.byName(_prefs.getString('theme') ?? 'system');
    baseUrl = _prefs.getString('baseUrl') ?? defaultBaseUrl;
    var guest = _prefs.getString('guestId');
    if (guest == null) {
      final r = Random.secure();
      const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
      guest = 'g_${List.generate(24, (_) => abc[r.nextInt(abc.length)]).join()}';
      await _prefs.setString('guestId', guest);
    }
    String? token;
    try {
      token = await _secure.read(key: 'token');
    } catch (_) {}
    api = Api(baseUrl: baseUrl, guestId: guest, token: token);
    tripId = _prefs.getString('tripId');
    ready = true;
    notifyListeners();
    await refreshMe();
    if (tripId != null) await openTrip(tripId!, quiet: true);
    if (messages.isEmpty) messages.add(ChatLine('assistant', tr('greeting')));
    refreshHome();
  }

  // ---------------------------------------------------------------- settings
  Future<void> setLang(String l) async {
    lang = l;
    currentLang = l;
    await _prefs.setString('lang', l);
    if (messages.length == 1 && messages.first.role == 'assistant' && tripId == null) {
      messages
        ..clear()
        ..add(ChatLine('assistant', tr('greeting')));
    }
    notifyListeners();
  }

  Future<void> setTheme(ThemeMode m) async {
    themeMode = m;
    await _prefs.setString('theme', m.name);
    notifyListeners();
  }

  Future<bool> setBaseUrl(String url) async {
    baseUrl = url.trim();
    api.baseUrl = baseUrl;
    await _prefs.setString('baseUrl', baseUrl);
    notifyListeners();
    return ping();
  }

  Future<bool> ping() async {
    try {
      await api.get('/api/health');
      return true;
    } catch (_) {
      return false;
    }
  }

  // ---------------------------------------------------------------- account
  Future<void> refreshMe() async {
    try {
      final r = await api.get('/api/auth/me');
      user = r['user'] as Map<String, dynamic>?;
      if (user == null && api.token != null) await _setToken(null); // expired session
    } catch (_) {}
    notifyListeners();
  }

  Future<void> _setToken(String? t) async {
    api.token = t;
    try {
      if (t == null) {
        await _secure.delete(key: 'token');
      } else {
        await _secure.write(key: 'token', value: t);
      }
    } catch (_) {}
  }

  Future<void> auth({required bool signUp, String name = '', required String email, required String password}) async {
    final r = await api.post(signUp ? '/api/auth/signup' : '/api/auth/signin',
        signUp ? {'name': name, 'email': email, 'password': password} : {'email': email, 'password': password});
    await _setToken(r['token'] as String?);
    user = r['user'] as Map<String, dynamic>;
    notifyListeners();
    refreshHome();
  }

  Future<void> signOut() async {
    try {
      await api.post('/api/auth/signout');
    } catch (_) {}
    await _setToken(null);
    user = null;
    newTrip();
    refreshHome();
  }

  Future<void> updateProfile(Map<String, dynamic> body) async {
    final r = await api.patch('/api/me', body);
    user = r['user'] as Map<String, dynamic>;
    notifyListeners();
    refreshHome();
  }

  Future<void> changePassword(String current, String next) =>
      api.post('/api/me/password', {'current': current, 'new': next});

  Future<void> deleteAccount(String password) async {
    await api.delete('/api/me', body: {'password': password});
    await _setToken(null);
    user = null;
    newTrip();
    refreshHome();
  }

  // ---------------------------------------------------------------- home data
  Future<void> refreshHome() async {
    try {
      recs = await api.get('/api/recommendations', query: {'limit': '8'}) as Map<String, dynamic>;
    } catch (_) {
      recs = null;
    }
    try {
      trips = await api.get('/api/trips') as List<dynamic>;
    } catch (_) {}
    notifyListeners();
  }

  void logActivity(String kind, String city) {
    api.post('/api/activity', {'kind': kind, 'city': city}).catchError((_) => null);
  }

  Future<void> undoDismiss(String city) async {
    try {
      await api.delete('/api/activity/dismiss', query: {'city': city});
    } catch (_) {}
    refreshHome();
  }

  // ---------------------------------------------------------------- trips + chat
  /// Which conversation a running turn belongs to: switching trips retires it, so its answer never lands on
  /// another trip.
  int _gen = 0;

  void newTrip() {
    _retireTurn();
    tripId = null;
    trip = null;
    messages
      ..clear()
      ..add(ChatLine('assistant', tr('greeting')));
    _prefs.remove('tripId');
    notifyListeners();
  }

  void _retireTurn() {
    _gen++;
    busy = false;
    progress = null;
  }

  Future<bool> openTrip(String id, {bool quiet = false}) async {
    try {
      final t = await api.get('/api/trips/$id') as Map<String, dynamic>;
      if (id != tripId) _retireTurn();
      _setTrip(t);
      messages.clear();
      final conv = (t['conversation'] as List? ?? []);
      for (var i = 0; i < conv.length; i++) {
        final m = conv[i] as Map<String, dynamic>;
        messages.add(ChatLine(m['role'] as String, m['content'] as String? ?? '',
            tripCard: i == conv.length - 1 && m['role'] == 'assistant' && plan != null));
      }
      if (messages.isEmpty) messages.add(ChatLine('assistant', tr('greeting')));
      notifyListeners();
      return true;
    } catch (e) {
      // Forget the trip only when the server says it's gone (or not ours) - never when offline or still starting.
      if (quiet && e is ApiException && (e.status == 404 || e.status == 403)) {
        tripId = null;
        _prefs.remove('tripId');
      }
      return false;
    }
  }

  void _setTrip(Map<String, dynamic> t) {
    trip = t;
    tripId = t['trip_id'] as String;
    _prefs.setString('tripId', tripId!);
  }

  /// Sends a chat message; false when it wasn't sent (a turn is still running, or nothing to send).
  Future<bool> send(String text) async {
    if (text.trim().isEmpty || busy) return false;
    messages.add(ChatLine('user', text.trim()));
    busy = true;
    progress = Progress()..add('understand');
    notifyListeners();
    final gen = _gen;
    var gotReply = false;
    await for (final ev in api.chatStream(text.trim(), tripId: tripId)) {
      if (gen != _gen) continue; // the traveller switched trips: this answer belongs to the old one
      if (ev.type == 'node') {
        final k = _nodeSteps[ev.data['node']];
        if (k != null) progress!.add(k);
      } else if (ev.type == 'tool') {
        final k = _toolSteps[ev.data['server']];
        if (k != null) progress!.add(k);
      } else if (ev.type == 'done' && !gotReply) {
        final t = ev.data['trip'] as Map<String, dynamic>;
        _setTrip(t);
        final reply = ev.data['reply'] as String? ?? '';
        if (reply.isNotEmpty) messages.add(ChatLine('assistant', reply, tripCard: plan != null));
        gotReply = true;
      } else if (ev.type == 'error') {
        messages.add(ChatLine('assistant', _errorText(ev.data)));
        gotReply = true; // a later 'done' (if any) is ignored: the turn failed
      }
      notifyListeners();
    }
    if (gen != _gen) return true;
    if (!gotReply) messages.add(ChatLine('assistant', tr('errPlan')));
    busy = false;
    progress = null;
    notifyListeners();
    refreshHome();
    return true;
  }

  String _errorText(Map<String, dynamic> e) {
    final status = e['status'];
    if (status == 429) return tr('errRate', [e['retry'] ?? 60]);
    if (status == 400 || status == 422) return tr('errTooLong');
    return e['message'] == 'network' || e['message'] == 'timeout' ? tr('errNet') : tr('errPlan');
  }

  Future<void> selectMode(String mode) async {
    if (tripId == null || busy) return; // a running turn would overwrite the choice
    final t = await api.post('/api/trips/$tripId/select', {'mode': mode}) as Map<String, dynamic>;
    trip = t;
    notifyListeners();
  }

  Future<void> deleteTrip(String id) async {
    await api.delete('/api/trips/$id');
    if (id == tripId) newTrip();
    trips.removeWhere((x) => x['trip_id'] == id);
    notifyListeners();
    refreshHome();
  }

  void goTab(int i) {
    tab = i;
    notifyListeners();
  }
}
