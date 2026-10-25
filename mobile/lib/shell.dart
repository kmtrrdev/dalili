import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

/// Links that leave the site (a hotel's page, Wikipedia, a ticket office) open in the browser, never inside the app.
bool isExternal(Uri link, Uri server) =>
    (link.scheme == 'http' || link.scheme == 'https') && link.host != server.host;

/// The page to open first: the Arabic site for an Arabic phone (or a traveller who chose Arabic in the old app).
Uri startPage(Uri server, String? lang, String deviceLang) =>
    server.replace(path: (lang ?? deviceLang) == 'ar' ? '/ar' : '/');

/// Android's web view reports no safe area, so the site's bottom bar would sit under the gesture line: the app tells the
/// site how tall that strip is (the bar keeps its colour down to the edge, its buttons sit above it). iOS reports its own.
String bottomInsetScript(bool android, double bottom) => android && bottom > 0
    ? "document.documentElement.style.setProperty('--sab-app', '${bottom.toStringAsFixed(1)}px');"
    : '';

/// The native part of the app around the website: the back button, the camera and the gallery for the landmark
/// camera, links out to the browser, a screen when there is no connection - and, on the first start after the update,
/// the traveller's trips and sign-in carried over from the previous version of the app.
class Shell extends StatefulWidget {
  const Shell({super.key, required this.server});
  final Uri server;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  late final WebViewController _web;
  bool _offline = false;
  bool _loading = true;
  String? _carryOver; // localStorage to restore once the first page is loaded (the previous app's open trip, theme)

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF04060C))
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: (req) {
          final link = Uri.tryParse(req.url);
          if (link != null && isExternal(link, widget.server)) {
            launchUrl(link, mode: LaunchMode.externalApplication);
            return NavigationDecision.prevent;
          }
          return NavigationDecision.navigate;
        },
        onPageStarted: (_) => setState(() => _loading = true),
        onPageFinished: (_) => _finished(),
        onWebResourceError: (e) {
          if (e.isForMainFrame ?? true) setState(() => _offline = true);
        },
      ));
    final platform = _web.platform;
    if (platform is AndroidWebViewController) {
      platform.setOnShowFileSelector(_pickPhoto); // <input type="file"> - iOS's web view offers it by itself
      platform.setMediaPlaybackRequiresUserGesture(true);
    }
    unawaited(_start());
  }

  /// Carries the previous app's guest id and sign-in into the website's cookies (so no trip and no account is lost),
  /// then opens the site in the traveller's language.
  Future<void> _start() async {
    final prefs = await SharedPreferences.getInstance();
    final lang = prefs.getString('lang');
    if (!(prefs.getBool('shellMigrated') ?? false)) {
      final cookies = WebViewCookieManager();
      final guest = prefs.getString('guestId');
      String? token;
      try {
        token = await const FlutterSecureStorage().read(key: 'token');
      } catch (_) {
        token = null; // keystore unavailable: the traveller signs in again
      }
      final host = widget.server.host;
      if (guest != null) {
        await cookies.setCookie(WebViewCookie(name: 'dalili_guest', value: guest, domain: host));
      }
      if (token != null) {
        await cookies.setCookie(WebViewCookie(name: 'dalili_session', value: token, domain: host));
      }
      final keep = {
        'tripId': ?prefs.getString('tripId'),
        if (prefs.getString('theme') == 'light') 'theme': 'light',
        'lang': ?lang,
      };
      if (keep.isNotEmpty) {
        _carryOver = keep.entries.map((e) => "localStorage.setItem('${e.key}', '${e.value.replaceAll("'", '')}');").join();
      }
      await prefs.setBool('shellMigrated', true);
    }
    if (!mounted) return;
    final device = WidgetsBinding.instance.platformDispatcher.locale.languageCode;
    await _web.loadRequest(startPage(widget.server, lang, device));
  }

  Future<void> _finished() async {
    setState(() => _loading = false);
    final inset = bottomInsetScript(_web.platform is AndroidWebViewController, MediaQuery.viewPaddingOf(context).bottom);
    if (inset.isNotEmpty) await _web.runJavaScript(inset);
    final script = _carryOver;
    if (script != null) {
      _carryOver = null;
      await _web.runJavaScript(script);
      await _web.reload(); // the site starts again with the restored trip
    }
  }

  /// The camera or the gallery, for the landmark camera's photo.
  Future<List<String>> _pickPhoto(FileSelectorParams params) async {
    final arabic = Localizations.localeOf(context).languageCode == 'ar' ||
        WidgetsBinding.instance.platformDispatcher.locale.languageCode == 'ar';
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: const Color(0xFF0E1731),
      builder: (context) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text(arabic ? 'صوّر' : 'Take a photo'),
              onTap: () => Navigator.pop(context, ImageSource.camera)),
          ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: Text(arabic ? 'من الصور' : 'Choose from photos'),
              onTap: () => Navigator.pop(context, ImageSource.gallery)),
        ]),
      ),
    );
    if (source == null) return [];
    final photo = await ImagePicker().pickImage(source: source, maxWidth: 2000, imageQuality: 90);
    return photo == null ? [] : [Uri.file(photo.path).toString()];
  }

  Future<void> _back() async {
    if (await _web.canGoBack()) {
      await _web.goBack();
    } else {
      await SystemNavigator.pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final arabic = WidgetsBinding.instance.platformDispatcher.locale.languageCode == 'ar';
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        body: SafeArea(
          bottom: false,
          child: _offline
              ? _Offline(arabic: arabic, retry: () {
                  setState(() => _offline = false);
                  _web.reload();
                })
              : Stack(children: [
                  WebViewWidget(controller: _web),
                  if (_loading) const LinearProgressIndicator(minHeight: 2, color: Color(0xFF3DE0D0)),
                ]),
        ),
      ),
    );
  }
}

class _Offline extends StatelessWidget {
  const _Offline({required this.arabic, required this.retry});
  final bool arabic;
  final VoidCallback retry;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.wifi_off_rounded, size: 48, color: Color(0xFF3DE0D0)),
            const SizedBox(height: 14),
            Text(arabic ? 'مفيش اتصال بالإنترنت' : 'No internet connection',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(arabic ? 'اتأكد من الاتصال وجرّب تاني.' : 'Check your connection and try again.',
                textAlign: TextAlign.center, style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 18),
            FilledButton(onPressed: retry, child: Text(arabic ? 'جرّب تاني' : 'Try again')),
          ]),
        ),
      );
}
