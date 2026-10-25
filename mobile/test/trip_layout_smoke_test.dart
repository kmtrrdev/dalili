import 'package:dalili/core/api.dart';
import 'package:dalili/core/i18n.dart';
import 'package:dalili/core/state.dart';
import 'package:dalili/core/theme.dart';
import 'package:dalili/screens/trip_screen.dart';
import 'package:dalili/screens/wallet_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/date_symbol_data_local.dart';

// Lays My trip and the wallet out at phone widths, both languages, larger text, dark and light: any overflow fails.

Map<String, dynamic> _plan(String mode, num total) => {
      'mode': mode,
      'pitch': 'The best of the city at an easy pace, with the famous sights in the mornings and long dinners.',
      'pitch_ar': 'أحسن ما في المدينة على راحتك.',
      'outbound_flight': {
        'id': 'fl_1', 'mode': 'flight', 'airline': 'EgyptAir', 'flight_number': 'MS 791', 'origin': 'CAI', 'destination': 'FCO',
        'depart_at': '2026-11-02T09:15:00+02:00', 'arrive_at': '2026-11-02T12:40:00+01:00', 'duration_minutes': 265, 'stops': 0,
        'price_per_person': {'amount': 412, 'currency': 'USD'}, 'booking_url': 'https://example.com',
      },
      'return_flight': {
        'id': 'fl_2', 'airline': 'ITA Airways', 'flight_number': 'AZ 894', 'origin': 'FCO', 'destination': 'CAI',
        'depart_at': '2026-11-07T18:00:00+01:00', 'arrive_at': '2026-11-07T22:30:00+02:00', 'duration_minutes': 210, 'stops': 1, 'via': 'ATH',
        'price_per_person': {'amount': 398, 'currency': 'USD'},
      },
      'hotel': {
        'id': 'h1', 'name': 'Hotel Artemide Roma with a very long name indeed', 'neighborhood': 'Esquilino', 'rating': 4.6, 'stars': 4,
        'reviews_count': 3021, 'location': {'lat': 41.9, 'lon': 12.49}, 'price_per_night': {'amount': 2480, 'currency': 'EGP'},
        'total_price': {'amount': 12400, 'currency': 'EGP'}, 'breakfast_included': true, 'images': <String>[], 'link': 'https://x.y',
        'review_insights': {'summary': 'Guests love the staff and the location.', 'summary_ar': 'الضيوف بيحبوا المكان.'},
      },
      'days': [
        for (var d = 1; d <= 6; d++)
          {
            'day': d, 'date': '2026-11-0${d + 1}', 'title': 'Ancient Rome and the Colosseum, then Trastevere at night', 'walking_km': 7.4,
            'estimated_cost': {'amount': 120, 'currency': 'USD'}, 'city': 'Rome',
            'weather': {'date': '2026-11-0${d + 1}', 'condition': 'Partly cloudy', 'temp_min_c': 11 + d, 'temp_max_c': 19 + d, 'precipitation_probability': 30},
            'notes': ['Book the Colosseum ahead.'],
            'items': [
              {'start': '09:00', 'end': '11:30', 'kind': 'activity', 'title': 'Colosseum and the Roman Forum with Palatine Hill',
                'cost': {'amount': 18, 'currency': 'EUR', 'price_type': 'known'}, 'location': {'lat': 41.89, 'lon': 12.49},
                'notes': 'Arrive early to beat the queues; the combined ticket covers the Forum and Palatine Hill. ' * 2},
              {'start': '12:00', 'end': '13:15', 'kind': 'meal', 'title': 'Lunch at Trattoria da Enzo', 'link': 'https://menu',
                'cost': {'amount': 25, 'currency': 'EUR', 'price_type': 'estimated'}, 'location': {'lat': 41.88, 'lon': 12.47},
                'transport_from_previous': {'mode': 'walk', 'minutes': 14, 'distance_km': 1.1, 'cost': {'amount': 0, 'currency': 'EUR'}}},
            ],
          },
      ],
      'budget': {
        'currency': 'USD', 'flights': 1620, 'hotel': 1100, 'food': 600, 'activities': 300, 'transport': 120, 'buffer': 160,
        'total': total, 'limit': 4000, 'remaining': 4000 - total, 'daily_spending': {for (var d = 2; d <= 7; d++) '2026-11-0$d': 100 + d * 20},
        'by_trust': {'verified': 2500, 'calculated': 400, 'estimated': 900}, 'notes': ['Prices include a buffer.'],
      },
      'score': {'total': 87},
    };

AppState _state() {
  final s = AppState();
  s.api = Api(baseUrl: 'http://127.0.0.1:9', guestId: 'g_test');
  s.tripId = 'trip_abc123def4';
  s.trip = {
    'trip_id': 'trip_abc123def4',
    'selected_mode': 'balanced',
    'trip_contract': {
      'origin_city': 'Cairo', 'destination': 'Rome', 'destination_name': 'Rome', 'start_date': '2026-11-02', 'end_date': '2026-11-07',
      'travelers': 2, 'budget': {'amount': 4000, 'currency': 'USD'}, 'destination_ref': {'lat': 41.9, 'lon': 12.5},
    },
    'plans': {'balanced': _plan('balanced', 3900), 'budget': _plan('budget', 3100), 'comfort': _plan('comfort', 4600)},
    'metadata': {
      'event_offers': [
        {'name': 'Rome Film Festival', 'name_ar': 'مهرجان روما السينمائي', 'category': 'festival', 'city': 'Rome', 'country_code': 'IT',
          'event_dates': ['2026-10-28', '2026-11-08'], 'trip_days': ['2026-11-02', '2026-11-07'], 'why': 'A red carpet week in the city.',
          'ticket': {'amount': 15, 'currency': 'EUR', 'source': 'official site'}, 'url': 'https://x', 'place': {'id': 'wev_Q1'}},
      ],
    },
  };
  s.trips = [
    {'trip_id': 'a', 'cities': ['Rome'], 'status': 'planned', 'start_date': '2026-11-02', 'end_date': '2026-11-07', 'days': 6, 'travelers': 2,
      'origin': 'Cairo', 'mode': 'balanced', 'total': 3900, 'currency': 'USD', 'score': 87},
    {'trip_id': 'b', 'cities': ['Riyadh', 'Istanbul'], 'status': 'planned', 'start_date': '2025-01-02', 'end_date': '2025-01-09', 'days': 8,
      'origin': 'Cairo', 'mode': 'comfort', 'total': 52000, 'currency': 'EGP', 'score': 91},
    {'trip_id': 'c', 'cities': <String>[], 'status': 'collecting'},
  ];
  return s;
}

void main() {
  setUpAll(() async {
    // No network in tests: the fonts fall back to the test font, which draws every letter as a 1em square - wider
    // than the real faces, so passing here is a strict overflow check.
    GoogleFonts.config.allowRuntimeFetching = false;
    await initializeDateFormatting('en');
    await initializeDateFormatting('ar');
  });

  for (final lang in ['en', 'ar']) {
    for (final (w, scale) in [(360.0, 1.0), (360.0, 1.3), (440.0, 1.0)]) {
      for (final dark in [true, false]) {
        testWidgets('trip + wallet lay out: $lang ${w}px x$scale ${dark ? 'dark' : 'light'}', (tester) async {
          currentLang = lang;
          tester.view.physicalSize = Size(w * 3, 800 * 3);
          tester.view.devicePixelRatio = 3;
          addTearDown(tester.view.reset);
          final st = _state();
          Widget app(Widget home) => MaterialApp(
                theme: buildTheme(dark ? Brightness.dark : Brightness.light, lang),
                locale: Locale(lang),
                builder: (context, child) => MediaQuery(
                  data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
                  child: Directionality(textDirection: lang == 'ar' ? TextDirection.rtl : TextDirection.ltr, child: child!),
                ),
                home: home,
              );
          await tester.pumpWidget(app(TripScreen(state: st)));
          for (var i = 0; i < 20; i++) {
            await tester.pump(const Duration(milliseconds: 100));
          }
          // Scroll through, open each section.
          for (final s in ['tabStay', 'tabBudget', 'tabWeather', 'tabPlan']) {
            final f = find.text(tr(s));
            if (f.evaluate().isNotEmpty) {
              await tester.ensureVisible(f.first);
              await tester.pump();
              await tester.tap(f.first, warnIfMissed: false);
              for (var i = 0; i < 15; i++) {
                await tester.pump(const Duration(milliseconds: 100));
              }
            }
            await tester.drag(find.byType(CustomScrollView), const Offset(0, -900));
            for (var i = 0; i < 10; i++) {
              await tester.pump(const Duration(milliseconds: 100));
            }
          }
          await tester.pumpWidget(app(WalletScreen(state: st)));
          for (var i = 0; i < 20; i++) {
            await tester.pump(const Duration(milliseconds: 100));
          }
          await tester.pumpWidget(const SizedBox());
          await tester.pump(const Duration(seconds: 2));
        });
      }
    }
  }
}
