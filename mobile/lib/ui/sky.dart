import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../core/theme.dart';

/// The app's backdrop: a night sky with faint stars (or a pale morning sky), dotted flight paths and tiny planes
/// crossing them, and a soft aurora glow. It moves slowly and costs little (one painter, its own layer).
class SkyBackground extends StatefulWidget {
  const SkyBackground({super.key, this.child, this.planes = 3, this.glow = DC.teal});
  final Widget? child;
  final int planes;
  final Color glow;

  @override
  State<SkyBackground> createState() => _SkyBackgroundState();
}

class _SkyBackgroundState extends State<SkyBackground> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 40))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dark = context.dark;
    return Stack(children: [
      Positioned.fill(
        child: RepaintBoundary(
          child: CustomPaint(painter: _SkyPainter(_c, dark, widget.planes, widget.glow)),
        ),
      ),
      if (widget.child != null) widget.child!,
    ]);
  }
}

class _SkyPainter extends CustomPainter {
  _SkyPainter(this.t, this.dark, this.planes, this.glow) : super(repaint: t);
  final Animation<double> t;
  final bool dark;
  final int planes;
  final Color glow;

  static final _stars = List.generate(70, (i) {
    final r = math.Random(i * 7919);
    return (r.nextDouble(), r.nextDouble(), .4 + r.nextDouble() * 1.2, r.nextDouble());
  });

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    canvas.drawRect(
      rect,
      Paint()
        ..shader = ui.Gradient.linear(rect.topCenter, rect.bottomCenter, dark
            ? const [Color(0xFF0A1226), Color(0xFF060912), Color(0xFF05070E)]
            : const [Color(0xFFDDE8F7), Color(0xFFEAEFF7), Color(0xFFF3F0E8)], const [0, .55, 1]),
    );
    final v = t.value;
    // Aurora: two slow blobs.
    for (final (i, c) in [(0, glow), (1, DC.violet)]) {
      final a = v * 2 * math.pi + i * 2.4;
      final center = Offset(size.width * (.3 + .4 * (i == 0 ? math.sin(a) : math.cos(a)) * .5 + i * .3), size.height * (.12 + i * .22));
      canvas.drawCircle(
        center,
        size.width * .7,
        Paint()
          ..shader = ui.Gradient.radial(center, size.width * .7,
              [c.withValues(alpha: dark ? .16 : .14), c.withValues(alpha: 0)]),
      );
    }
    if (dark) {
      final sp = Paint();
      for (final (x, y, r, phase) in _stars) {
        final tw = .35 + .65 * (.5 + .5 * math.sin((v * 12 + phase * 6) * math.pi));
        sp.color = Colors.white.withValues(alpha: .55 * tw);
        canvas.drawCircle(Offset(x * size.width, y * size.height * .8), r, sp);
      }
    }
    // Flight paths: dotted arcs with a plane flying along each.
    final dot = Paint()..color = (dark ? Colors.white : const Color(0xFF1C3460)).withValues(alpha: dark ? .10 : .10);
    for (var i = 0; i < planes; i++) {
      final y0 = size.height * (.18 + i * .27);
      final from = Offset(-size.width * .1, y0 + size.height * .1);
      final to = Offset(size.width * 1.1, y0 - size.height * .04);
      final ctrl = Offset(size.width * .5, y0 - size.height * (.12 + .04 * i));
      Offset at(double s) {
        final a = (1 - s) * (1 - s), b = 2 * (1 - s) * s, c = s * s;
        return Offset(a * from.dx + b * ctrl.dx + c * to.dx, a * from.dy + b * ctrl.dy + c * to.dy);
      }

      for (var s = 0.0; s <= 1; s += .018) {
        canvas.drawCircle(at(s), 1.3, dot);
      }
      final s = (v * (1 + i * .35) + i * .31) % 1;
      final p = at(s), q = at(math.min(1, s + .01));
      _plane(canvas, p, math.atan2(q.dy - p.dy, q.dx - p.dx), dark ? Colors.white.withValues(alpha: .5) : const Color(0xFF1C3460).withValues(alpha: .35));
    }
  }

  static void _plane(Canvas canvas, Offset at, double angle, Color color) {
    canvas.save();
    canvas.translate(at.dx, at.dy);
    canvas.rotate(angle);
    final path = Path()
      ..moveTo(7, 0)
      ..lineTo(-5, -1.2)
      ..lineTo(-7, -5)
      ..lineTo(-8.5, -5)
      ..lineTo(-7.5, -1)
      ..lineTo(-8.5, 0)
      ..lineTo(-7.5, 1)
      ..lineTo(-8.5, 5)
      ..lineTo(-7, 5)
      ..lineTo(-5, 1.2)
      ..close()
      ..moveTo(1, -1)
      ..lineTo(-3, -7)
      ..lineTo(-1.5, -7)
      ..lineTo(3, -1)
      ..moveTo(1, 1)
      ..lineTo(-3, 7)
      ..lineTo(-1.5, 7)
      ..lineTo(3, 1);
    canvas.drawPath(path, Paint()..color = color);
    canvas.restore();
  }

  @override
  bool shouldRepaint(_SkyPainter old) => old.dark != dark || old.planes != planes || old.glow != glow;
}

/// A flight route drawn on a pass: a dotted arc from one code to the other with a plane on it at [progress] (0..1),
/// a glowing trail behind the plane. Mirrored in Arabic (the trip reads right to left).
class RouteArc extends StatelessWidget {
  const RouteArc({super.key, required this.progress, this.color = DC.teal, this.height = 54});
  final double progress;
  final Color color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final rtl = Directionality.of(context) == TextDirection.rtl;
    return SizedBox(
      height: height,
      width: double.infinity,
      child: CustomPaint(painter: _ArcPainter(progress, color, rtl, context.dark ? Colors.white24 : const Color(0x44000000))),
    );
  }
}

class _ArcPainter extends CustomPainter {
  _ArcPainter(this.p, this.color, this.rtl, this.dots);
  final double p;
  final Color color;
  final bool rtl;
  final Color dots;

  @override
  void paint(Canvas canvas, Size size) {
    if (rtl) {
      canvas.translate(size.width, 0);
      canvas.scale(-1, 1);
    }
    final from = Offset(6, size.height - 6), to = Offset(size.width - 6, size.height - 6);
    final ctrl = Offset(size.width / 2, -size.height * .55);
    Offset at(double s) {
      final a = (1 - s) * (1 - s), b = 2 * (1 - s) * s, c = s * s;
      return Offset(a * from.dx + b * ctrl.dx + c * to.dx, a * from.dy + b * ctrl.dy + c * to.dy);
    }

    final dot = Paint()..color = dots;
    for (var s = 0.0; s <= 1.0001; s += .04) {
      canvas.drawCircle(at(s), 1.4, dot);
    }
    final trail = Path()..moveTo(from.dx, from.dy);
    for (var s = 0.0; s <= p; s += .01) {
      final o = at(s);
      trail.lineTo(o.dx, o.dy);
    }
    canvas.drawPath(trail, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2
      ..strokeCap = StrokeCap.round
      ..shader = ui.Gradient.linear(from, at(p), [color.withValues(alpha: 0), color]));
    canvas.drawCircle(from, 4, Paint()..color = color);
    canvas.drawCircle(to, 4, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..color = color);
    final o = at(p.clamp(0.0, 1.0)), q = at(math.min(1, p + .01));
    canvas.drawCircle(o, 12, Paint()..color = color.withValues(alpha: .18));
    _SkyPainter._plane(canvas, o, math.atan2(q.dy - o.dy, q.dx - o.dx) + (p >= 1 ? 0 : 0), color);
  }

  @override
  bool shouldRepaint(_ArcPainter old) => old.p != p || old.color != color || old.rtl != rtl;
}

/// Plays a [RouteArc] once from 0 to 1 (the plane takes off when the pass appears).
class FlyingRoute extends StatelessWidget {
  const FlyingRoute({super.key, this.color = DC.teal, this.height = 54, this.to = 1});
  final Color color;
  final double height;
  final double to;

  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: to),
        duration: const Duration(milliseconds: 1600),
        curve: Curves.easeInOutCubic,
        builder: (_, v, _) => RouteArc(progress: v, color: color, height: height),
      );
}
