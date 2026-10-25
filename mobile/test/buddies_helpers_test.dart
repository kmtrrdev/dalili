import 'package:dalili/screens/buddies_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('initials: first name + initial, one letter for Arabic names', () {
    expect(buddyInitials('Mona H.'), 'MH');
    expect(buddyInitials('sara'), 'S');
    expect(buddyInitials('منى ح.'), 'م');
    expect(buddyInitials(''), '?');
    expect(buddyInitials(null), '?');
  });

  test('merging keeps one copy per id, oldest first, sending ones last, local flags kept', () {
    final have = <Map<String, dynamic>>[
      {'id': 5, 'text': 'b', 'reported': true},
      {'id': 3, 'text': 'a'},
      {'_key': 'tmp1', 'text': 'sending', 'sending': true},
    ];
    final out = mergeBuddyMessages(have, [
      {'id': 5, 'text': 'b'},
      {'id': 7, 'text': 'c'},
      'junk',
    ]);
    expect(out.map((m) => m['text']), ['a', 'b', 'c', 'sending']);
    expect(out[1]['reported'], true);
  });

  test('a message the server stops sending in the re-read window is hidden', () {
    expect(hiddenBuddyIds(known: [1, 4, 5, 6, 9], returned: [5, 9], after: 3, upTo: 1 << 52), {4, 6});
    // Beyond what the server returned (its page limit), nothing is judged.
    expect(hiddenBuddyIds(known: [4, 5, 6, 9], returned: [4, 5], after: 3, upTo: 5), isEmpty);
  });

  test('a city whose dates are behind us is over; today is not', () {
    final now = DateTime(2026, 10, 26, 15);
    expect(stopIsOver('2026-10-25', now), isTrue);
    expect(stopIsOver('2026-10-26', now), isFalse);
    expect(stopIsOver(null, now), isFalse);
  });

  test('system messages: leaving, Dalili\'s welcome, other notes', () {
    expect(buddySystemKind('👋 Mona H. left the group.'), 'left');
    expect(buddySystemKind('👋 Welcome Ali! You both love food.'), 'welcome');
    expect(buddySystemKind('Group created'), 'note');
  });

  test('a name always gets the same colour', () {
    expect(buddyColor('Mona H.'), buddyColor('Mona H.'));
  });
}
