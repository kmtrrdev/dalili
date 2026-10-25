import 'package:dalili/core/i18n.dart';
import 'package:dalili/screens/trip_helpers.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  setUp(() => currentLang = 'en');

  test('a pass prints the airport code, else the city', () {
    expect(passCode('FCO', 'Rome'), 'FCO');
    expect(passCode('/m/06c62', 'Rome'), 'Rome');
    expect(passCode(null, null), '—');
    expect(isAirportCode('cai'), isFalse);
  });

  test('flight times are the published wall-clock time', () {
    expect(clockOf('2026-10-12T01:30:00+03:00'), '01:30');
    expect(clockOf('nope'), '');
    expect(durationLabel(125), '2h 05');
    expect(durationLabel(45), '45m');
    expect(nightsBetween('2026-10-01', '2026-10-06'), 5);
  });

  test('a tour lists its legs once, labelled outbound / leg / return', () {
    final plan = {
      'legs': [
        {'id': 'a'}, {'id': 'b'}, {'id': 'c'},
      ],
      'outbound_flight': {'id': 'a'},
      'return_flight': {'id': 'c'},
    };
    final f = planFlights(plan);
    expect(f.map((e) => e.$1), ['Outbound', 'Leg 2', 'Return']);
    expect(planFlights({'outbound_flight': {'id': 'x'}}).single.$1, 'Outbound');
  });

  test('hotels: one per stop on a tour, else the plan hotel', () {
    expect(planHotels({'hotel': {'name': 'H'}}).single.$1, isNull);
    final tour = planHotels({
      'stops': [
        {'name': 'Rome', 'hotel': {'name': 'A'}},
        {'name': 'Florence', 'hotel': null},
      ],
    });
    expect(tour.map((e) => e.$1), ['Rome']);
  });

  test('cities and the day an offered event is planned on', () {
    expect(tripCities({'trip_contract': {'destination_name': 'Paris'}}), ['Paris']);
    expect(
        tripCities({
          'trip_contract': {
            'stops': [
              {'ref': {'name': 'Riyadh'}},
              {'ref': {'name': 'Istanbul'}},
            ],
          },
        }),
        ['Riyadh', 'Istanbul']);
    final plan = {
      'days': [
        {'day': 1, 'items': [{'place_id': 'p1'}]},
        {'day': 2, 'items': [{'place_id': 'wev_Q1'}]},
      ],
    };
    expect(dayOfPlace(plan, 'wev_Q1'), 2);
    expect(dayOfPlace(plan, 'missing'), isNull);
  });

  test('wallet filters', () {
    final trips = [
      {'trip_id': 'a', 'status': 'planned', 'start_date': '2026-12-01', 'end_date': '2026-12-05'},
      {'trip_id': 'b', 'status': 'planned', 'start_date': '2026-01-01', 'end_date': '2026-01-05'},
      {'trip_id': 'c', 'status': 'collecting'},
    ];
    String ids(String f) => filterTrips(trips, f, '2026-10-26').map((t) => t['trip_id']).join();
    expect(ids('all'), 'abc');
    expect(ids('upcoming'), 'a');
    expect(ids('past'), 'b');
    expect(ids('drafts'), 'c');
  });

  test('what-if step follows the budget, at least 50', () {
    expect(whatIfStep(1000), 50);
    expect(whatIfStep(40000), 1000);
    expect(whatIfStep(null), 50);
  });
}
