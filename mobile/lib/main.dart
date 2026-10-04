import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'core/i18n.dart';
import 'core/state.dart';
import 'core/theme.dart';
import 'screens/chat_screen.dart';
import 'screens/home_screen.dart';
import 'screens/profile_screen.dart';
import 'screens/trips_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
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
          home: state.ready ? Shell(state: state) : const _Splash(),
        ),
      );
}

class _Splash extends StatelessWidget {
  const _Splash();
  @override
  Widget build(BuildContext context) => const Scaffold(
        backgroundColor: DC.night,
        body: Center(child: Icon(Icons.flight_rounded, color: DC.teal, size: 56)),
      );
}

/// The four tabs. Each keeps its scroll position while you switch (IndexedStack).
class Shell extends StatelessWidget {
  const Shell({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    SystemChrome.setSystemUIOverlayStyle(dark ? SystemUiOverlayStyle.light : SystemUiOverlayStyle.dark);
    return Scaffold(
      body: IndexedStack(index: state.tab, children: [
        HomeScreen(state: state),
        ChatScreen(state: state),
        TripsScreen(state: state),
        ProfileScreen(state: state),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: state.tab,
        onDestinationSelected: (i) {
          state.goTab(i);
          if (i == 2 || i == 0) state.refreshHome();
        },
        destinations: [
          NavigationDestination(icon: const Icon(Icons.explore_outlined), selectedIcon: const Icon(Icons.explore_rounded), label: tr('tabExplore')),
          NavigationDestination(
            icon: Badge(isLabelVisible: state.busy, backgroundColor: DC.teal, child: const Icon(Icons.chat_bubble_outline_rounded)),
            selectedIcon: const Icon(Icons.chat_bubble_rounded),
            label: tr('tabChat'),
          ),
          NavigationDestination(icon: const Icon(Icons.luggage_outlined), selectedIcon: const Icon(Icons.luggage_rounded), label: tr('tabTrips')),
          NavigationDestination(icon: const Icon(Icons.person_outline_rounded), selectedIcon: const Icon(Icons.person_rounded), label: tr('tabProfile')),
        ],
      ),
    );
  }
}
