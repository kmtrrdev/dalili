import 'package:dalili/screens/pilgrimage_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final days = {
    '2026-10-26': {
      'times': {'Fajr': '05:01', 'Dhuhr': '11:58', 'Asr': '15:17', 'Maghrib': '17:43', 'Isha': '19:13'},
    },
    '2026-10-27': {
      'times': {'Fajr': '05:02', 'Dhuhr': '11:58', 'Asr': '15:17', 'Maghrib': '17:42', 'Isha': '19:12'},
    },
  };

  group('makkahNow', () {
    test('is UTC+3 whatever the phone zone', () {
      final n = makkahNow(DateTime.utc(2026, 10, 26, 22, 30));
      expect(isoDay(n), '2026-10-27');
      expect(n.hour, 1);
    });
  });

  group('nextPrayer', () {
    test('the next one today', () {
      final p = nextPrayer(days, DateTime.utc(2026, 10, 26, 12, 0))!;
      expect(p.key, 'Asr');
      expect(p.day, '2026-10-26');
    });
    test('after Isha it is tomorrow\'s Fajr', () {
      final p = nextPrayer(days, DateTime.utc(2026, 10, 26, 20, 0))!;
      expect(p.key, 'Fajr');
      expect(p.day, '2026-10-27');
      expect(p.at, DateTime.utc(2026, 10, 27, 5, 2));
    });
    test('null past the last day', () {
      expect(nextPrayer(days, DateTime.utc(2026, 10, 28)), isNull);
    });
  });

  group('umrahMessage (the website\'s pgMsg)', () {
    test('English', () {
      expect(
        umrahMessage(arabic: false, nights: 7, makkah: 5, date: '9 November 2026', pax: 2, budget: '2,500 USD', from: 'Cairo'),
        'I want to do Umrah: 7 nights from 9 November 2026 (5 in Makkah, 2 in Madinah) for 2 travellers, budget 2,500 USD, flying from Cairo',
      );
    });
    test('Arabic, one traveller, Makkah only, no budget', () {
      expect(
        umrahMessage(arabic: true, nights: 4, makkah: 9, date: '9 نوفمبر 2026', pax: 1, from: 'القاهرة'),
        'عايز أعمل عمرة: 4 ليالي من 9 نوفمبر 2026 (4 في مكة) لـ 1 فرد، مسافر من القاهرة',
      );
    });
    test('Arabic with Madinah and budget', () {
      expect(
        umrahMessage(arabic: true, nights: 7, makkah: 5, date: 'D', pax: 3, budget: ' 3000 ', from: 'جدة'),
        'عايز أعمل عمرة: 7 ليالي من D (5 في مكة و2 في المدينة) لـ 3 أفراد، الميزانية 3000، مسافر من جدة',
      );
    });
  });

  test('countdownText', () {
    expect(countdownText(const Duration(hours: 2, minutes: 4, seconds: 9)), '02:04:09');
    expect(countdownText(const Duration(seconds: -3)), '00:00:00');
  });
}
