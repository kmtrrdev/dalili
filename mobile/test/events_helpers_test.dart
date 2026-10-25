import 'dart:convert';
import 'dart:typed_data';

import 'package:dalili/core/i18n.dart';
import 'package:dalili/core/state.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:dalili/screens/events_screen.dart';
import 'package:dalili/screens/landmark_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/date_symbol_data_local.dart';

Map<String, dynamic> ev(String id, String start, String end, {int fame = 0, String source = 'wikidata'}) => {
      'id': id, 'name': 'Event $id', 'name_ar': 'إيفنت $id', 'category': 'sports', 'city': 'Monaco', 'city_ar': 'موناكو',
      'country_code': 'MC', 'start': start, 'end': end, 'dates_source': source, 'fame': fame, 'ticket': null,
      'wikipedia': 'https://en.wikipedia.org/wiki/Monaco_Grand_Prix',
    };

void main() {
  setUpAll(() async {
    GoogleFonts.config.allowRuntimeFetching = false;
    await initializeDateFormatting('en');
    await initializeDateFormatting('ar');
  });

  test('events are grouped by the month they start in, in date order then by fame', () {
    final g = groupByMonth([
      ev('b', '2026-12-10', '2026-12-12'),
      ev('a', '2026-11-03', '2026-11-03', fame: 1),
      ev('c', '2026-11-03', '2026-11-05', fame: 9),
    ]);
    expect(g.map((x) => x.$1), ['2026-11', '2026-12']);
    expect(g.first.$2.map((e) => e['id']), ['c', 'a']);
  });

  test('dates, place and the plan message read like the website', () {
    currentLang = 'en';
    final e = ev('x', '2026-06-05', '2026-06-07');
    expect(eventSpan(e), '5 Jun – 7 Jun 2026');
    expect(eventSpan(ev('y', '2026-06-05', '2026-06-05')), '5 Jun 2026');
    expect(eventPlace(e), 'Monaco, Monaco');
    expect(eventPlanMessage(e), 'Plan a trip to Monaco, Monaco to attend Event x (5 Jun – 7 Jun 2026)');
    expect(ticketText(e), 'Free or see the site');
    currentLang = 'ar';
    expect(eventName(e), 'إيفنت x');
    expect(eventPlace(e), 'موناكو، موناكو');
    expect(eventPlanMessage(e), startsWith('عايز أسافر موناكو، موناكو عشان أحضر إيفنت x'));
    currentLang = 'en';
  });

  test('usual dates are not confirmed; on-now covers the whole span', () {
    expect(datesConfirmed(ev('a', '2026-01-01', '2026-01-02', source: 'usual dates')), isFalse);
    expect(datesConfirmed(ev('a', '2026-01-01', '2026-01-02')), isTrue);
    final e = ev('a', '2026-01-01', '2026-01-03');
    expect(eventOnNow(e, DateTime(2026, 1, 3, 22)), isTrue);
    expect(eventOnNow(e, DateTime(2026, 1, 4)), isFalse);
  });

  test('flags and country names', () {
    expect(flagOf('eg'), '🇪🇬');
    expect(flagOf('x'), '');
    currentLang = 'en';
    expect(countryName('EG'), 'Egypt');
    expect(countryName('ZZ'), 'ZZ');
  });

  test('photo type and coordinates', () {
    expect(imageMime(Uint8List.fromList([0x89, 0x50, 0x4E, 0x47, 0, 0])), 'image/png');
    expect(imageMime(Uint8List.fromList([0xFF, 0xD8, 0xFF, 0xE0])), 'image/jpeg');
    expect(coordText(30.04442, -31.2357), '30.0444°N  31.2357°W');
  });

  for (final lang in ['en', 'ar']) {
    testWidgets('an event ticket fits a narrow phone with large text ($lang)', (tester) async {
      currentLang = lang;
      tester.view.physicalSize = const Size(360 * 3, 800 * 3);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        home: Directionality(
          textDirection: lang == 'ar' ? TextDirection.rtl : TextDirection.ltr,
          child: MediaQuery(
            data: const MediaQueryData(size: Size(360, 800), textScaler: TextScaler.linear(1.3)),
            child: Scaffold(
              body: ListView(padding: const EdgeInsets.all(16), children: [
                EventTicket(event: ev('q1', '2026-11-28', '2026-12-06', source: 'usual dates'), onTap: () {}),
              ]),
            ),
          ),
        ),
      ));
      await tester.pump(const Duration(milliseconds: 50));
      expect(tester.takeException(), isNull);
      expect(find.text('NOV'), findsOneWidget);
    });

    Future<void> narrow(WidgetTester tester, Widget child) async {
      tester.view.physicalSize = const Size(360 * 3, 760 * 3);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        locale: Locale(lang),
        supportedLocales: const [Locale('en'), Locale('ar')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        // The test font draws every glyph 1em wide (real fonts ~0.55em), so 0.75 here is about 1.35x real text.
        builder: (context, c) => MediaQuery(
          data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(.75)),
          child: c!,
        ),
        home: child,
      ));
      for (var i = 0; i < 20; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
    }

    testWidgets('the events tab and an event sheet lay out at 360 px ($lang)', (tester) async {
      currentLang = lang;
      final state = AppState(); // no api: the load fails and the error state shows
      await narrow(tester, EventsScreen(state: state));
      expect(tester.takeException(), isNull);
      await narrow(tester, Scaffold(
        body: EventDetailSheet(event: ev('q2', '2026-11-28', '2026-12-06', source: 'usual dates'), onPlan: () {}),
      ));
      expect(tester.takeException(), isNull);
    });

    testWidgets('the landmark camera lays out at 360 px ($lang)', (tester) async {
      currentLang = lang;
      await narrow(tester, LandmarkScreen(state: AppState()));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox()); // stop the endless sky / float animations
    });

    testWidgets('a recognised landmark (low confidence) lays out at 360 px ($lang)', (tester) async {
      currentLang = lang;
      final png = base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==');
      final place = <String, dynamic>{
        'found': true, 'name': 'Cairo Citadel', 'name_ar': 'قلعة صلاح الدين', 'city': 'Cairo', 'country_code': 'EG',
        'lat': 30.0299, 'lon': 31.2611, 'image': null, 'wikipedia': 'https://en.wikipedia.org/wiki/Cairo_Citadel',
        'seen': 'A large stone fortress with two slim minarets on a hill', 'confidence': 'low',
        'alternatives': ['Mosque of Muhammad Ali, a very long alternative title to wrap'],
        'guide': {
          'name': lang == 'ar' ? 'قلعة صلاح الدين' : 'Cairo Citadel',
          'summary': 'A medieval Islamic-era fortification in Cairo, Egypt, built by **Salah ad-Din**.',
          'history': ['1176: construction begins', '1830s: the Mosque of Muhammad Ali is built'],
          'tips': ['Go early to avoid the heat'],
          'questions': ['Who built it?', 'Can I climb the walls?', 'What is inside the mosque?'],
        },
      };
      await narrow(tester, LandmarkScreen(state: AppState(), debugResult: (place, png)));
      expect(tester.takeException(), isNull);
      expect(find.text('Best guess', skipOffstage: false), lang == 'en' ? findsWidgets : findsNothing);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
