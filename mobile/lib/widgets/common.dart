import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart' hide TextDirection;
import 'package:url_launcher/url_launcher.dart';

import '../core/i18n.dart';
import '../core/theme.dart';

// ---------------------------------------------------------------- formatting
String money(num? amount, String? cur) {
  if (amount == null) return '–';
  const sym = {'USD': r'$', 'EUR': '€', 'GBP': '£'};
  final n = NumberFormat.decimalPattern('en').format(amount.round());
  final s = sym[cur];
  final out = s != null ? '$s$n' : '$n ${cur ?? ''}'.trim();
  // Isolate the amount left-to-right so "$1,284" never flips inside Arabic text.
  return isArabic ? '\u2066$out\u2069' : out;
}

String fmtDate(String? iso, {bool year = false}) {
  if (iso == null || iso.isEmpty) return '';
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  return DateFormat(year ? 'd MMM y' : 'd MMM', isArabic ? 'ar' : 'en').format(d);
}

String routeText(List<dynamic> cities) => cities.map((c) => '$c').join(isArabic ? ' ← ' : ' → ');

Future<void> openLink(String? url) async {
  if (url == null || url.isEmpty) return;
  await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
}

void toast(BuildContext context, String msg, {String? action, VoidCallback? onAction}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(msg),
      action: action == null ? null : SnackBarAction(label: action, onPressed: onAction ?? () {}),
    ));
}

// ---------------------------------------------------------------- place photos (Wikipedia lead photo, JPEG only)
final Map<String, Future<String?>> _photoCache = {};
const _imgHeaders = {'User-Agent': 'Dalili/2.0 (graduation project; Flutter app)'};

Future<String?> placePhoto(String title) => _photoCache.putIfAbsent(title, () async {
      try {
        final r = await http.get(Uri.parse(
            'https://en.wikipedia.org/api/rest_v1/page/summary/${Uri.encodeComponent(title.replaceAll(' ', '_'))}'),
            headers: {'User-Agent': 'Dalili/2.0 (graduation project)'});
        final j = jsonDecode(r.body) as Map<String, dynamic>;
        final src = ((j['originalimage'] ?? j['thumbnail']) as Map?)?['source'] as String?;
        if (src == null || !RegExp(r'\.jpe?g', caseSensitive: false).hasMatch(src)) return null; // photos only
        // Wikimedia only serves its standard thumbnail sizes, so use the thumbnail URL exactly as given.
        final thumb = (j['thumbnail'] as Map?)?['source'] as String?;
        return (thumb != null && RegExp(r'\.jpe?g', caseSensitive: false).hasMatch(thumb)) ? thumb : src;
      } catch (e) {
        debugPrint('photo lookup failed for $title: $e');
        return null;
      }
    });

/// A photo that fades in; a coloured gradient with an emoji while it loads (or if there is none).
class PlacePhoto extends StatelessWidget {
  const PlacePhoto({super.key, this.url, this.title, this.emoji = '✈️', this.tint = DC.teal, this.radius = 0, this.height});
  final String? url;
  final String? title;
  final String emoji;
  final Color tint;
  final double radius;
  final double? height;

  @override
  Widget build(BuildContext context) {
    final fallback = Container(
      height: height,
      decoration: BoxDecoration(
          gradient: LinearGradient(colors: [Color.lerp(tint, Colors.black, .35)!, const Color(0xFF1A1E3A)],
              begin: Alignment.topLeft, end: Alignment.bottomRight)),
      alignment: Alignment.center,
      child: Text(emoji, style: const TextStyle(fontSize: 34)),
    );
    // Wikimedia refuses image requests without an identifying User-Agent.
    Widget img(String u) => Image.network(u, headers: _imgHeaders, height: height, width: double.infinity, fit: BoxFit.cover,
        frameBuilder: (_, child, frame, sync) => sync
            ? child
            : AnimatedOpacity(opacity: frame == null ? 0 : 1, duration: const Duration(milliseconds: 350), child: child),
        errorBuilder: (_, e, _) {
          debugPrint('image failed $u: $e');
          return fallback;
        });
    Widget child;
    if (url != null && url!.isNotEmpty) {
      child = Stack(fit: StackFit.passthrough, children: [fallback, Positioned.fill(child: img(url!))]);
    } else if (title != null) {
      child = FutureBuilder<String?>(
        future: placePhoto(title!),
        builder: (_, s) => s.data == null ? fallback : Stack(fit: StackFit.passthrough, children: [fallback, Positioned.fill(child: img(s.data!))]),
      );
    } else {
      child = fallback;
    }
    return ClipRRect(borderRadius: BorderRadius.circular(radius), child: child);
  }
}

// ---------------------------------------------------------------- small building blocks
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.subtitle, this.action, this.onAction});
  final String title;
  final String? subtitle;
  final String? action;
  final VoidCallback? onAction;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 26, 12, 12),
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              if (subtitle != null)
                Padding(padding: const EdgeInsets.only(top: 2),
                    child: Text(subtitle!, style: TextStyle(color: context.muted, fontSize: 13))),
            ]),
          ),
          if (action != null) TextButton(onPressed: onAction, child: Text(action!)),
        ]),
      );
}

class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.color, this.icon, this.solid = false});
  final String text;
  final Color? color;
  final IconData? icon;
  final bool solid;
  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.primary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: solid ? c : c.withValues(alpha: context.dark ? .16 : .12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) ...[Icon(icon, size: 13, color: solid ? Colors.white : c), const SizedBox(width: 4)],
        Text(text, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: solid ? Colors.white : c)),
      ]),
    );
  }
}

/// A big gradient call-to-action button.
class BrandButton extends StatelessWidget {
  const BrandButton({super.key, required this.label, required this.onTap, this.icon, this.busy = false});
  final String label;
  final VoidCallback? onTap;
  final IconData? icon;
  final bool busy;
  @override
  Widget build(BuildContext context) => Opacity(
        opacity: onTap == null ? .5 : 1,
        child: DecoratedBox(
          decoration: BoxDecoration(gradient: DC.brand, borderRadius: BorderRadius.circular(16),
              boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .28), blurRadius: 22, offset: const Offset(0, 8))]),
          child: Material(
            color: Colors.transparent,
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: busy ? null : onTap,
              child: SizedBox(
                height: 54,
                child: Center(
                  child: busy
                      ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: Color(0xFF04110F)))
                      : Row(mainAxisSize: MainAxisSize.min, children: [
                          if (icon != null) ...[Icon(icon, color: const Color(0xFF04110F), size: 20), const SizedBox(width: 8)],
                          Text(label, style: const TextStyle(color: Color(0xFF04110F), fontWeight: FontWeight.w800, fontSize: 16)),
                        ]),
                ),
              ),
            ),
          ),
        ),
      );
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.emoji, required this.title, this.subtitle, this.action, this.onAction});
  final String emoji;
  final String title;
  final String? subtitle;
  final String? action;
  final VoidCallback? onAction;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 48),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(emoji, style: const TextStyle(fontSize: 52)),
          const SizedBox(height: 12),
          Text(title, textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleLarge),
          if (subtitle != null) ...[
            const SizedBox(height: 6),
            Text(subtitle!, textAlign: TextAlign.center, style: TextStyle(color: context.muted)),
          ],
          if (action != null) ...[
            const SizedBox(height: 20),
            SizedBox(width: 240, child: BrandButton(label: action!, icon: Icons.add_rounded, onTap: onAction)),
          ],
        ]),
      );
}

/// Light markdown: **bold**, *italic*, "- " bullets, paragraphs. Text direction follows the text itself.
class MdText extends StatelessWidget {
  const MdText(this.text, {super.key, this.color, this.size = 15});
  final String text;
  final Color? color;
  final double size;

  List<InlineSpan> _inline(String s, TextStyle base) {
    final spans = <InlineSpan>[];
    final re = RegExp(r'\*\*(.+?)\*\*|\*(\S.*?)\*');
    var i = 0;
    for (final m in re.allMatches(s)) {
      if (m.start > i) spans.add(TextSpan(text: s.substring(i, m.start)));
      spans.add(m.group(1) != null
          ? TextSpan(text: m.group(1), style: const TextStyle(fontWeight: FontWeight.w800))
          : TextSpan(text: m.group(2), style: const TextStyle(fontStyle: FontStyle.italic)));
      i = m.end;
    }
    if (i < s.length) spans.add(TextSpan(text: s.substring(i)));
    return spans;
  }

  @override
  Widget build(BuildContext context) {
    final base = TextStyle(fontSize: size, height: 1.45, color: color ?? Theme.of(context).textTheme.bodyMedium?.color);
    final blocks = <Widget>[];
    for (final raw in text.split('\n')) {
      final line = raw.trimRight();
      if (line.trim().isEmpty) continue;
      final dir = RegExp(r'[؀-ۿ]').hasMatch(line) ? TextDirection.rtl : TextDirection.ltr;
      final bullet = RegExp(r'^\s*[-•]\s+').firstMatch(line);
      final body = bullet != null ? line.substring(bullet.end) : line.replaceFirst(RegExp(r'^#+\s*'), '');
      final rich = Text.rich(TextSpan(style: base, children: _inline(body, base)), textDirection: dir);
      blocks.add(Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: bullet == null
            ? rich
            : Row(textDirection: dir, crossAxisAlignment: CrossAxisAlignment.start, children: [
                Padding(padding: const EdgeInsets.only(top: 1, left: 2, right: 8), child: Text('•', style: base)),
                Expanded(child: rich),
              ]),
      ));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: blocks);
  }
}
