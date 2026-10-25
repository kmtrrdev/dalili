import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'core/state.dart';
import 'core/theme.dart';
import 'screens/chat_screen.dart';
import 'screens/events_screen.dart';
import 'screens/home_screen.dart';
import 'screens/profile_screen.dart';
import 'screens/trip_screen.dart';
import 'ui/dock.dart';
import 'ui/motion.dart';
import 'ui/sky.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  await initializeDateFormatting('en');
  await initializeDateFormatting('ar');
  final state = AppState();
  runApp(DaliliApp(state: state));
  await state.init();
}

class DaliliApp extends StatelessWidget {
  const DaliliApp({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: state,
        builder: (context, _) => MaterialApp(
          title: 'Dalili',
          debugShowCheckedModeBanner: false,
          locale: Locale(state.lang),
          supportedLocales: const [Locale('en'), Locale('ar')],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          themeMode: state.themeMode,
          theme: buildTheme(Brightness.light, state.lang),
          darkTheme: buildTheme(Brightness.dark, state.lang),
          home: AnimatedSwitcher(
            duration: const Duration(milliseconds: 600),
            child: state.ready ? Shell(state: state) : const _Splash(),
          ),
        ),
      );
}

/// The first second: a pass floating on the night sky.
class _Splash extends StatelessWidget {
  const _Splash();
  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: DC.night,
        body: Center(
          child: Float(
            child: Container(
              width: 92,
              height: 92,
              decoration: BoxDecoration(
                gradient: DC.brand,
                borderRadius: BorderRadius.circular(28),
                boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .4), blurRadius: 40)],
              ),
              child: Transform.rotate(angle: math.pi / 4, child: const Icon(Icons.flight_rounded, color: DC.onBrand, size: 46)),
            ),
          ),
        ),
      );
}

/// The five tabs over one animated sky, with the floating dock. Each tab keeps its place while you switch, and the
/// tab you open turns in with a light 3D swing.
class Shell extends StatelessWidget {
  const Shell({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final dark = context.dark;
    SystemChrome.setSystemUIOverlayStyle((dark ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark)
        .copyWith(statusBarColor: Colors.transparent, systemNavigationBarColor: Colors.transparent));
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    final tabs = [
      HomeScreen(state: state),
      TripScreen(state: state),
      ChatScreen(state: state),
      EventsScreen(state: state),
      ProfileScreen(state: state),
    ];
    return Scaffold(
      backgroundColor: dark ? DC.night : DC.day,
      resizeToAvoidBottomInset: true,
      body: SkyBackground(
        child: Stack(children: [
          Positioned.fill(
            child: IndexedStack(
              index: state.tab,
              children: [
                for (var i = 0; i < tabs.length; i++) _TabSwing(active: state.tab == i, child: tabs[i]),
              ],
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: AnimatedSlide(
              offset: keyboard ? const Offset(0, 1.6) : Offset.zero,
              duration: const Duration(milliseconds: 260),
              curve: Curves.easeOutCubic,
              child: Dock(state: state),
            ),
          ),
        ]),
      ),
    );
  }
}

/// Plays a short 3D swing-in each time its tab becomes the open one.
class _TabSwing extends StatefulWidget {
  const _TabSwing({required this.active, required this.child});
  final bool active;
  final Widget child;

  @override
  State<_TabSwing> createState() => _TabSwingState();
}

class _TabSwingState extends State<_TabSwing> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 420), value: 1);

  @override
  void didUpdateWidget(_TabSwing old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) _c.forward(from: 0);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) {
          final v = Curves.easeOutCubic.transform(_c.value);
          return Opacity(
            opacity: .4 + .6 * v,
            child: Transform(
              alignment: Alignment.center,
              transform: perspective()
                ..translateByDouble(0, (1 - v) * 24, 0, 1)
                ..rotateX((1 - v) * .12)
                ..scaleByDouble(.97 + .03 * v, .97 + .03 * v, 1, 1),
              child: child,
            ),
          );
        },
        child: widget.child,
      );
}
