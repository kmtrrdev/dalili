import 'package:dalili/screens/profile_screen.dart';
import 'package:dalili/screens/wizard_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('check digits follow ICAO 9303 (the specimen passport)', () {
    expect(mrzCheck('L898902C3'), '6');
    expect(mrzCheck('740812'), '2');
    expect(mrzCheck('120415'), '9');
  });

  test('names are written A-Z only, Arabic transliterated', () {
    expect(mrzName('Mohamed Hassan'), 'MOHAMED<HASSAN');
    expect(mrzName("  Anne-Marie O'Neil "), 'ANNE<MARIE<O<NEIL');
    expect(mrzName('محمد'), 'MHMD');
  });

  test('the machine-readable zone is two 44-character lines', () {
    final l = mrzLines(name: 'Mohamed Hassan', id: 'u_8f2a91c0', since: DateTime(2026, 3, 9));
    expect(l, hasLength(2));
    expect(l[0], startsWith('P<DLIHASSAN<<MOHAMED<'));
    expect(l.every((x) => x.length == 44), isTrue);
    expect(RegExp(r'^[A-Z0-9<]+$').hasMatch(l[0] + l[1]), isTrue);
    expect(l[1], contains('260309'));
    // An empty name still gives a valid zone.
    expect(mrzLines(name: '', id: 'x')[0], startsWith('P<DLITRAVELLER'));
  });

  test('a passport number is stable and 9 characters', () {
    expect(passportNo('u_8f2a91c0'), 'DLF2A91C0');
    expect(passportNo('ab'), 'DL00000AB');
  });

  test('stamps: one per city of a planned trip, the same look every time', () {
    final trips = [
      {'status': 'planned', 'cities': ['Rome', 'Florence'], 'start_date': '2026-05-02'},
      {'status': 'planned', 'cities': ['rome'], 'start_date': '2027-01-10'},
      {'status': 'collecting', 'cities': ['Paris'], 'start_date': null},
      {'status': 'planned', 'cities': ['القاهرة'], 'start_date': '2026-12-01'},
    ];
    final a = passportStamps(trips, today: DateTime(2026, 10, 26));
    expect(a.map((s) => s.city), ['Rome', 'Florence', 'القاهرة']);
    expect(a.first.code, 'ROM');
    expect(a.first.label, 'Rome · MAY 2026');
    expect(a.first.upcoming, isFalse);
    expect(a.last.upcoming, isTrue);
    expect(a.last.code, 'ALK'); // Latin letters for the ring's centre
    final b = passportStamps(trips, today: DateTime(2026, 10, 26));
    expect(b.first.angle, a.first.angle);
    expect(b.first.color, a.first.color);
    expect(a.every((s) => s.angle.abs() <= .3 && s.dx.abs() <= 6 && s.dy.abs() <= 6), isTrue);
  });

  test('pass codes: 3 letters for Latin names, the first word for Arabic ones', () {
    expect(passCode('Cairo'), 'CAI');
    expect(passCode('  '), '---');
    expect(passCode('Sharm El Sheikh'), 'SHA');
    expect(passCode('شرم الشيخ'), 'شرم');
  });
}
