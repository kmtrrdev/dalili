import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import '../core/theme.dart';

/// A pass: two parts with a perforated tear line between them and a half-circle notch bitten out of each edge at
/// that line. Vertical (stub below, a boarding pass) or horizontal (stub at the end, a concert ticket; mirrored in
/// Arabic). The notches always sit exactly on the line, whatever the parts' sizes, and the shadow follows the shape.
class Ticket extends StatelessWidget {
  const Ticket({
    super.key,
    required this.main,
    required this.stub,
    this.axis = Axis.vertical,
    this.color,
    this.gradient,
    this.radius = 22,
    this.notch = 13,
    this.gap = 22,
    this.elevation = 10,
    this.dashColor,
    this.borderColor,
    this.onTap,
  });

  final Widget main;
  final Widget stub;
  final Axis axis;
  final Color? color;
  final Gradient? gradient;
  final double radius;
  final double notch;
  final double gap; // the tear line's own strip
  final double elevation;
  final Color? dashColor;
  final Color? borderColor;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final rtl = Directionality.of(context) == TextDirection.rtl;
    Widget t = _TicketBox(
      axis: axis,
      mirrored: axis == Axis.horizontal && rtl,
      color: color ?? context.ticket,
      gradient: gradient,
      radius: radius,
      notch: notch,
      gap: gap,
      elevation: elevation,
      shadow: context.dark ? Colors.black : const Color(0xFF1C3460),
      dash: dashColor ?? (context.dark ? Colors.white.withValues(alpha: .16) : const Color(0x331C3460)),
      border: borderColor ?? context.ticketEdge,
      children: [main, stub],
    );
    if (onTap != null) {
      t = GestureDetector(behavior: HitTestBehavior.opaque, onTap: onTap, child: t);
    }
    return t;
  }
}

class _TicketBox extends MultiChildRenderObjectWidget {
  const _TicketBox({
    required this.axis,
    required this.mirrored,
    required this.color,
    required this.gradient,
    required this.radius,
    required this.notch,
    required this.gap,
    required this.elevation,
    required this.shadow,
    required this.dash,
    required this.border,
    required super.children,
  });

  final Axis axis;
  final bool mirrored;
  final Color color;
  final Gradient? gradient;
  final double radius, notch, gap, elevation;
  final Color shadow, dash, border;

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderTicket()..configure(this);

  @override
  void updateRenderObject(BuildContext context, _RenderTicket renderObject) => renderObject.configure(this);
}

class _TicketParentData extends ContainerBoxParentData<RenderBox> {}

class _RenderTicket extends RenderBox
    with ContainerRenderObjectMixin<RenderBox, _TicketParentData>, RenderBoxContainerDefaultsMixin<RenderBox, _TicketParentData> {
  Axis _axis = Axis.vertical;
  bool _mirrored = false;
  Color _color = Colors.white;
  Gradient? _gradient;
  double _radius = 22, _notch = 13, _gap = 22, _elevation = 10;
  Color _shadow = Colors.black, _dash = Colors.grey, _border = Colors.transparent;
  double _cut = 0; // where the tear line's centre is, along the main axis

  void configure(_TicketBox w) {
    final relayout = _axis != w.axis || _gap != w.gap || _mirrored != w.mirrored;
    _axis = w.axis;
    _mirrored = w.mirrored;
    _color = w.color;
    _gradient = w.gradient;
    _radius = w.radius;
    _notch = w.notch;
    _gap = w.gap;
    _elevation = w.elevation;
    _shadow = w.shadow;
    _dash = w.dash;
    _border = w.border;
    relayout ? markNeedsLayout() : markNeedsPaint();
  }

  @override
  void setupParentData(RenderBox child) {
    if (child.parentData is! _TicketParentData) child.parentData = _TicketParentData();
  }

  @override
  void performLayout() {
    final a = firstChild!, b = childAfter(a)!;
    final pa = a.parentData as _TicketParentData, pb = b.parentData as _TicketParentData;
    if (_axis == Axis.vertical) {
      final inner = BoxConstraints(maxWidth: constraints.maxWidth, minWidth: constraints.maxWidth.isFinite ? constraints.maxWidth : 0);
      a.layout(inner, parentUsesSize: true);
      b.layout(inner, parentUsesSize: true);
      final w = math.max(a.size.width, b.size.width);
      pa.offset = Offset.zero;
      pb.offset = Offset(0, a.size.height + _gap);
      _cut = a.size.height + _gap / 2;
      size = constraints.constrain(Size(w, a.size.height + _gap + b.size.height));
    } else {
      // The stub keeps its natural width; the main part takes the rest. Both get the taller one's height.
      b.layout(BoxConstraints(maxHeight: constraints.maxHeight), parentUsesSize: true);
      if (constraints.maxWidth.isFinite) {
        final w = math.max(0.0, constraints.maxWidth - b.size.width - _gap);
        a.layout(BoxConstraints(minWidth: w, maxWidth: w, maxHeight: constraints.maxHeight), parentUsesSize: true);
      } else {
        a.layout(BoxConstraints(maxHeight: constraints.maxHeight), parentUsesSize: true); // in a horizontal list
      }
      final mainW = a.size.width;
      final h = math.max(math.max(a.size.height, b.size.height), constraints.minHeight);
      a.layout(BoxConstraints.tightFor(width: mainW, height: h), parentUsesSize: true);
      b.layout(BoxConstraints.tightFor(width: b.size.width, height: h), parentUsesSize: true);
      final total = mainW + _gap + b.size.width;
      if (_mirrored) {
        pb.offset = Offset.zero;
        pa.offset = Offset(b.size.width + _gap, 0);
        _cut = b.size.width + _gap / 2;
      } else {
        pa.offset = Offset.zero;
        pb.offset = Offset(mainW + _gap, 0);
        _cut = mainW + _gap / 2;
      }
      size = constraints.constrain(Size(total, h));
    }
  }

  Path _shape(Offset o) {
    final r = Rect.fromLTWH(o.dx, o.dy, size.width, size.height);
    final body = Path()..addRRect(RRect.fromRectAndRadius(r, Radius.circular(_radius)));
    final bites = Path();
    if (_axis == Axis.vertical) {
      bites.addOval(Rect.fromCircle(center: Offset(r.left, r.top + _cut), radius: _notch));
      bites.addOval(Rect.fromCircle(center: Offset(r.right, r.top + _cut), radius: _notch));
    } else {
      bites.addOval(Rect.fromCircle(center: Offset(r.left + _cut, r.top), radius: _notch));
      bites.addOval(Rect.fromCircle(center: Offset(r.left + _cut, r.bottom), radius: _notch));
    }
    return Path.combine(PathOperation.difference, body, bites);
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final path = _shape(offset);
    var canvas = context.canvas;
    if (_elevation > 0) canvas.drawShadow(path, _shadow.withValues(alpha: .55), _elevation, false);
    final fill = Paint()..color = _color;
    if (_gradient != null) fill.shader = _gradient!.createShader(offset & size);
    canvas.drawPath(path, fill);
    context.pushClipPath(needsCompositing, offset, Offset.zero & size, _shape(Offset.zero), (ctx, o) {
      defaultPaint(ctx, o);
    });
    // A child with its own layer (a photo fading in, an Opacity) closes the canvas we had: take the current one.
    canvas = context.canvas;
    // The perforation: short dashes between the two notches.
    final dash = Paint()
      ..color = _dash
      ..strokeWidth = 1.6
      ..strokeCap = StrokeCap.round;
    if (_axis == Axis.vertical) {
      final y = offset.dy + _cut;
      for (var x = offset.dx + _notch + 8; x < offset.dx + size.width - _notch - 8; x += 10) {
        canvas.drawLine(Offset(x, y), Offset(math.min(x + 5, offset.dx + size.width - _notch - 8), y), dash);
      }
    } else {
      final x = offset.dx + _cut;
      for (var y = offset.dy + _notch + 8; y < offset.dy + size.height - _notch - 8; y += 10) {
        canvas.drawLine(Offset(x, y), Offset(x, math.min(y + 5, offset.dy + size.height - _notch - 8)), dash);
      }
    }
    canvas.drawPath(path, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = _border);
  }

  @override
  bool hitTestChildren(BoxHitTestResult result, {required Offset position}) =>
      defaultHitTestChildren(result, position: position);

  @override
  bool hitTestSelf(Offset position) => _shape(Offset.zero).contains(position);
}

/// The barcode at the bottom of a pass: bars drawn from the text (the same text always gives the same code).
class Barcode extends StatelessWidget {
  const Barcode(this.data, {super.key, this.height = 44, this.color});
  final String data;
  final double height;
  final Color? color;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: height,
        width: double.infinity,
        child: CustomPaint(painter: _BarcodePainter(data, color ?? context.ink.withValues(alpha: .85))),
      );
}

class _BarcodePainter extends CustomPainter {
  _BarcodePainter(this.data, this.color);
  final String data;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    var seed = data.codeUnits.fold<int>(7, (h, c) => (h * 31 + c) & 0x7fffffff);
    int next() => seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    final p = Paint()..color = color;
    var x = 0.0;
    while (x < size.width) {
      final w = 1.0 + (next() % 4);
      if (next() % 3 != 0) canvas.drawRect(Rect.fromLTWH(x, 0, w, size.height), p);
      x += w + 1 + (next() % 3);
    }
  }

  @override
  bool shouldRepaint(_BarcodePainter old) => old.data != data || old.color != color;
}

/// A small caps label above a value, like "GATE" / "B12" on a boarding pass.
class PassField extends StatelessWidget {
  const PassField(this.label, this.value, {super.key, this.end = false, this.valueColor, this.big = false});
  final String label;
  final String value;
  final bool end;
  final Color? valueColor;
  final bool big;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: end ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label.toUpperCase(), style: TextStyle(fontSize: 10, letterSpacing: 1.2, fontWeight: FontWeight.w800, color: context.faint)),
          const SizedBox(height: 3),
          Text(value, maxLines: 1, overflow: TextOverflow.ellipsis,
              style: display(size: big ? 22 : 15, weight: FontWeight.w700, color: valueColor ?? context.ink)),
        ],
      );
}

/// A round "stamp" (passport-stamp look): a ring of text around an emoji or a short word, slightly rotated.
class Stamp extends StatelessWidget {
  const Stamp({super.key, required this.label, required this.center, this.color = DC.rose, this.size = 86, this.angle = -.18});
  final String label;
  final String center;
  final Color color;
  final double size;
  final double angle;

  @override
  Widget build(BuildContext context) => Transform.rotate(
        angle: angle,
        child: SizedBox(
          width: size,
          height: size,
          child: CustomPaint(
            painter: _StampPainter(label.toUpperCase(), color),
            child: Center(child: Text(center, style: TextStyle(fontSize: size * .3, fontWeight: FontWeight.w900, color: color))),
          ),
        ),
      );
}

class _StampPainter extends CustomPainter {
  _StampPainter(this.label, this.color);
  final String label;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final r = size.width / 2;
    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..color = color.withValues(alpha: .85);
    canvas.drawCircle(c, r - 2, ring..strokeWidth = 2.4);
    canvas.drawCircle(c, r * .64, ring..strokeWidth = 1.2);
    final chars = label.characters.toList();
    if (chars.isEmpty) return;
    final step = (math.pi * 1.6) / math.max(1, chars.length - 1);
    for (var i = 0; i < chars.length; i++) {
      final a = -math.pi * 1.3 + step * i;
      final tp = TextPainter(
        text: TextSpan(text: chars[i], style: TextStyle(fontSize: size.width * .11, fontWeight: FontWeight.w900, color: color)),
        textDirection: TextDirection.ltr,
      )..layout();
      canvas.save();
      canvas.translate(c.dx + math.cos(a) * r * .82, c.dy + math.sin(a) * r * .82);
      canvas.rotate(a + math.pi / 2);
      tp.paint(canvas, Offset(-tp.width / 2, -tp.height / 2));
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(_StampPainter old) => old.label != label || old.color != color;
}
