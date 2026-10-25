import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/i18n.dart';
import '../core/theme.dart';

/// Pure readers of the trip JSON shared by My trip and the wallet (kept apart so they can be unit-tested).

const planModes = ['balanced', 'budget', 'comfort', 'experience'];

const modeIcon = {
  'balanced': Icons.balance_rounded,
  'budget': Icons.savings_rounded,
  'comfort': Icons.weekend_rounded,
  'experience': Icons.auto_awesome_rounded,
};

const kindIcon = {
  'flight': Icons.flight_rounded, 'transfer': Icons.local_taxi_rounded, 'hotel': Icons.hotel_rounded,
  'meal': Icons.restaurant_rounded, 'activity': Icons.place_rounded, 'free': Icons.wb_sunny_outlined,
  'rest': Icons.bed_rounded, 'transit': Icons.directions_transit_rounded,
};

const kindColor = {
  'flight': DC.sky, 'transfer': DC.amber, 'hotel': DC.violet, 'meal': DC.coral, 'activity': DC.teal,
  'free': DC.green, 'rest': DC.violet,
};

const legIcon = {
  'walk': Icons.directions_walk_rounded, 'transit': Icons.directions_transit_rounded, 'taxi': Icons.local_taxi_rounded,
  'train': Icons.train_rounded, 'bus': Icons.directions_bus_rounded,
};

/// A journey's own icon: most legs fly, but nearby stops of a tour can be a train, a coach or a drive.
IconData journeyIcon(String? mode) => switch (mode) {
      'train' => Icons.train_rounded,
      'coach' => Icons.directions_bus_rounded,
      'car' => Icons.directions_car_rounded,
      _ => Icons.flight_rounded,
    };

bool isAirportCode(String? s) => s != null && RegExp(r'^[A-Z]{3}$').hasMatch(s);

/// What a pass prints for one end of the route: the IATA code when the flight has one, else the city.
String passCode(String? code, String? city) {
  if (isAirportCode(code)) return code!;
  final c = (city ?? '').trim();
  if (c.isNotEmpty) return c;
  return (code ?? '').trim().isEmpty ? '—' : code!.trim();
}

/// "HH:MM" as published by the airline (the local wall-clock time in the ISO string, never converted).
String clockOf(String? iso) {
  if (iso == null || iso.length < 16 || DateTime.tryParse(iso) == null) return '';
  return iso.substring(11, 16);
}

String durationLabel(int minutes) {
  if (minutes <= 0) return '';
  final h = minutes ~/ 60, m = (minutes % 60).toString().padLeft(2, '0');
  if (h == 0) return L('${minutes}m', '$minutes د');
  return L('${h}h $m', '$hس $m');
}

int nightsBetween(String? start, String? end) {
  final a = DateTime.tryParse(start ?? ''), b = DateTime.tryParse(end ?? '');
  if (a == null || b == null) return 0;
  return math.max(0, b.difference(a).inDays);
}

/// How sure a price is: published (✓, or the menu average), an official tariff, a published range, or an estimate.
String priceTypeLabel(String? type, {bool menu = false}) => switch (type) {
      'estimated' => tr('est'),
      'calculated' => tr('tariff'),
      'range' => tr('range'),
      _ => menu ? tr('menuPrice') : '✓',
    };

IconData weatherIcon(String? condition) {
  final s = (condition ?? '').toLowerCase();
  if (s.contains('thunder') || s.contains('storm')) return Icons.thunderstorm_rounded;
  if (s.contains('rain') || s.contains('drizzle') || s.contains('shower')) return Icons.water_drop_rounded;
  if (s.contains('snow')) return Icons.ac_unit_rounded;
  if (s.contains('clear') || s.contains('sun')) return Icons.wb_sunny_rounded;
  return Icons.cloud_rounded;
}

Map<String, dynamic>? asMap(Object? o) => o is Map ? o.cast<String, dynamic>() : null;

List<Map<String, dynamic>> asMaps(Object? o) =>
    o is List ? [for (final x in o) if (x is Map) x.cast<String, dynamic>()] : const [];

/// The plan's journeys with their label. A tour lists its legs (the first is the outbound flight, the last the flight
/// home); its outbound / return are the same objects again, so they are not listed twice.
List<(String, Map<String, dynamic>)> planFlights(Map<String, dynamic> plan) {
  final legs = asMaps(plan['legs']);
  if (legs.isNotEmpty) {
    return [
      for (var i = 0; i < legs.length; i++)
        (i == 0 ? tr('outbound') : i == legs.length - 1 ? tr('return') : L('Leg ${i + 1}', 'المرحلة ${i + 1}'), legs[i]),
    ];
  }
  return [
    if (asMap(plan['outbound_flight']) != null) (tr('outbound'), asMap(plan['outbound_flight'])!),
    if (asMap(plan['return_flight']) != null) (tr('return'), asMap(plan['return_flight'])!),
  ];
}

/// Every city's hotel on a tour (with the city), else the one hotel.
List<(String?, Map<String, dynamic>)> planHotels(Map<String, dynamic> plan) {
  final stops = asMaps(plan['stops']);
  if (stops.isNotEmpty) {
    return [for (final s in stops) if (asMap(s['hotel']) != null) (s['name'] as String?, asMap(s['hotel'])!)];
  }
  final h = asMap(plan['hotel']);
  return h == null ? const [] : [(null, h)];
}

/// The trip's cities in order (a tour's stops, else the destination).
List<String> tripCities(Map<String, dynamic> trip) {
  final c = asMap(trip['trip_contract']) ?? const {};
  final stops = asMaps(c['stops']);
  final names = [for (final s in stops) '${asMap(s['ref'])?['name'] ?? ''}'.trim()].where((x) => x.isNotEmpty).toList();
  if (names.isNotEmpty) return names;
  final d = '${c['destination_name'] ?? ''}'.trim().isNotEmpty ? '${c['destination_name']}' : '${c['destination'] ?? ''}';
  return d.trim().isEmpty ? const [] : [d.trim()];
}

/// The day an item of the plan uses this place on (events offered during the trip), or null.
int? dayOfPlace(Map<String, dynamic>? plan, String? placeId) {
  if (plan == null || placeId == null) return null;
  for (final d in asMaps(plan['days'])) {
    for (final it in asMaps(d['items'])) {
      if (it['place_id'] == placeId) return (d['day'] as num?)?.toInt();
    }
  }
  return null;
}

/// The wallet's filters, as on the old trips list: upcoming / past only count planned trips; drafts are the rest.
List<Map<String, dynamic>> filterTrips(List<dynamic> trips, String filter, String today) {
  final all = [for (final t in trips) if (t is Map) t.cast<String, dynamic>()];
  return switch (filter) {
    'upcoming' => all.where((t) => t['status'] == 'planned' && '${t['start_date'] ?? ''}'.compareTo(today) >= 0).toList(),
    'past' => all.where((t) => t['status'] == 'planned' && '${t['end_date'] ?? '9'}'.compareTo(today) < 0).toList(),
    'drafts' => all.where((t) => t['status'] != 'planned').toList(),
    _ => all,
  };
}

/// The what-if slider's step, as on the website: about a fortieth of the budget, in fifties.
double whatIfStep(num? budget) => math.max(50, ((budget ?? 0) / 40 / 50).round() * 50).toDouble();

/// The budget's parts in display order: (i18n key, JSON key, colour, icon).
const budgetParts = [
  ('bFlights', 'flights', DC.sky, Icons.flight_rounded),
  ('bHotel', 'hotel', DC.violet, Icons.hotel_rounded),
  ('bFood', 'food', DC.coral, Icons.restaurant_rounded),
  ('bActivities', 'activities', DC.teal, Icons.place_rounded),
  ('bTransport', 'transport', DC.amber, Icons.directions_bus_rounded),
  ('bBuffer', 'buffer', DC.green, Icons.savings_rounded),
];
