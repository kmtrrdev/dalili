import 'package:dalili/core/i18n.dart';
import 'package:dalili/widgets/common.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

void main() {
  test('strings exist in both languages and fill their arguments', () {
    currentLang = 'en';
    expect(tr('match', [97]), '97% match');
    currentLang = 'ar';
    expect(tr('match', [97]), 'تطابق 97%');
    expect(tr('no.such.key'), 'no.such.key');
  });

  test('money formats like the website', () {
    currentLang = 'en';
    expect(money(1234.4, 'USD'), r'$1,234');
    expect(money(900, 'EGP'), '900 EGP');
    expect(money(null, 'USD'), '–');
    // In Arabic the amount is isolated left-to-right so "$1,234" never flips.
    currentLang = 'ar';
    expect(money(1234.4, 'USD'), '\u2066\$1,234\u2069');
  });

  test('amounts typed with Arabic digits or separators are understood', () {
    expect(parseAmount('٥٠٬٠٠٠'), 50000);
    expect(parseAmount('50,000'), 50000);
    expect(parseAmount('۲۵۰۰'), 2500);
    expect(parseAmount('abc'), isNull);
  });

  test('a flight date is the local date written in it, never shifted by the time zone', () async {
    await initializeDateFormatting('en');
    currentLang = 'en';
    expect(fmtDate('2026-10-12T01:30:00+03:00'), '12 Oct');
    expect(fmtDate('2026-10-12'), '12 Oct');
  });

  testWidgets('light markdown renders bold text and bullets', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: MdText('**Ready!**\n- first\n- second'))));
    expect(find.textContaining('Ready!', findRichText: true), findsOneWidget);
    expect(find.text('•'), findsNWidgets(2));
  });
}
