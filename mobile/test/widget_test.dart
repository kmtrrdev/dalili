import 'package:dalili/shell.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final server = Uri.parse('https://dalili.example.app');

  test('links out of the site open in the browser; the site stays in the app', () {
    expect(isExternal(Uri.parse('https://en.wikipedia.org/wiki/Petra'), server), isTrue);
    expect(isExternal(Uri.parse('https://dalili.example.app/static/js/app.js'), server), isFalse);
    expect(isExternal(Uri.parse('about:blank'), server), isFalse);
    expect(isExternal(Uri.parse('data:image/jpeg;base64,AAAA'), server), isFalse);
  });

  test('the first page follows the language chosen before, else the phone', () {
    expect(startPage(server, null, 'ar').path, '/ar');
    expect(startPage(server, 'en', 'ar').path, '/');
    expect(startPage(server, null, 'en').toString(), 'https://dalili.example.app/');
  });

  test('on Android the site is told how tall the gesture strip is; iOS reports its own', () {
    expect(bottomInsetScript(true, 24), contains("'--sab-app', '24.0px'"));
    expect(bottomInsetScript(true, 0), isEmpty);
    expect(bottomInsetScript(false, 34), isEmpty);
  });
}
