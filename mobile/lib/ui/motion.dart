import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';
import 'package:flutter/services.dart';

/// The 3D perspective every tilted / flipped surface uses.
Matrix4 perspective() => Matrix4.identity()..setEntry(3, 2, 0.0012);

/// A surface you can tilt with your finger: it leans toward the touch in 3D, a soft glare follows it, and it springs
/// back flat when you let go. Taps still reach the child.
class Tilt3D extends StatefulWidget {
  const Tilt3D({super.key, required this.child, this.maxAngle = .22, this.glare = true, this.radius = 22, this.lift = true});
  final Widget child;
  final double maxAngle;
  final bool glare;
  final double radius;
  final bool lift; // scale up slightly while held

  @override
  State<Tilt3D> createState() => _Tilt3DState();
}

class _Tilt3DState extends State<Tilt3D> with SingleTickerProviderStateMixin {
  Offset _tilt = Offset.zero; // -1..1 on both axes
  Offset _from = Offset.zero;
  late final AnimationController _back = AnimationController.unbounded(vsync: this)..addListener(_springStep);
  bool _held = false;

  void _springStep() => setState(() => _tilt = _from * (1 - _back.value));

  void _move(Offset local, Size size) {
    _back.stop();
    setState(() {
      _held = true;
      _tilt = Offset(((local.dx / size.width) * 2 - 1).clamp(-1.0, 1.0), ((local.dy / size.height) * 2 - 1).clamp(-1.0, 1.0));
    });
  }

  void _release() {
    _from = _tilt;
    _held = false;
    _back.value = 0;
    _back.animateWith(SpringSimulation(const SpringDescription(mass: 1, stiffness: 180, damping: 12), 0, 1, 0));
  }

  @override
  void dispose() {
    _back.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, c) {
        final size = Size(c.maxWidth.isFinite ? c.maxWidth : 300, c.maxHeight.isFinite ? c.maxHeight : 200);
        final m = perspective()
          ..rotateX(-_tilt.dy * widget.maxAngle)
          ..rotateY(_tilt.dx * widget.maxAngle);
        if (widget.lift && _held) m.scaleByDouble(1.025, 1.025, 1, 1);
        return Listener(
          onPointerDown: (e) => _move(e.localPosition, context.size ?? size),
          onPointerMove: (e) => _move(e.localPosition, context.size ?? size),
          onPointerUp: (_) => _release(),
          onPointerCancel: (_) => _release(),
          child: Transform(
            alignment: Alignment.center,
            transform: m,
            child: Stack(fit: StackFit.passthrough, children: [ // the child keeps the space it was given
              widget.child,
              if (widget.glare && _tilt != Offset.zero)
                Positioned.fill(
                  child: IgnorePointer(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(widget.radius),
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          gradient: RadialGradient(
                            center: Alignment(_tilt.dx, _tilt.dy),
                            radius: 1.1,
                            colors: [Colors.white.withValues(alpha: .18 * _tilt.distance.clamp(0, 1)), Colors.transparent],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            ]),
          ),
        );
      });
}

/// A card with two faces that turns over in 3D (tap, or set [flipped]).
class FlipCard extends StatefulWidget {
  const FlipCard({super.key, required this.front, required this.back, this.flipped, this.onFlip, this.tapToFlip = true});
  final Widget front;
  final Widget back;
  final bool? flipped; // controlled when set
  final ValueChanged<bool>? onFlip;
  final bool tapToFlip;

  @override
  State<FlipCard> createState() => _FlipCardState();
}

class _FlipCardState extends State<FlipCard> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 650),
      value: (widget.flipped ?? false) ? 1 : 0);

  @override
  void didUpdateWidget(FlipCard old) {
    super.didUpdateWidget(old);
    if (widget.flipped != null && widget.flipped != old.flipped) _go(widget.flipped!);
  }

  void _go(bool back) {
    HapticFeedback.selectionClick();
    back ? _c.animateTo(1, curve: Curves.easeInOutBack) : _c.animateTo(0, curve: Curves.easeInOutBack);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: widget.tapToFlip
            ? () {
                final next = _c.value < .5;
                if (widget.flipped == null) _go(next);
                widget.onFlip?.call(next);
              }
            : null,
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) {
            final a = _c.value * math.pi;
            final showBack = a > math.pi / 2;
            return Transform(
              alignment: Alignment.center,
              transform: perspective()..rotateY(a),
              child: showBack
                  ? Transform(alignment: Alignment.center, transform: Matrix4.rotationY(math.pi), child: widget.back)
                  : widget.front,
            );
          },
        ),
      );
}

/// Coverflow for a PageView page: the pages beside the current one turn away in 3D, shrink and fade.
/// Use inside a PageView.builder: `Coverflow(controller: c, index: i, child: ...)`.
class Coverflow extends StatelessWidget {
  const Coverflow({super.key, required this.controller, required this.index, required this.child, this.turn = .42});
  final PageController controller;
  final int index;
  final Widget child;
  final double turn;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: controller,
        builder: (context, child) {
          var page = index.toDouble();
          if (controller.hasClients && controller.position.haveDimensions) page = controller.page ?? page;
          final d = (index - page).clamp(-1.5, 1.5);
          final rtl = Directionality.of(context) == TextDirection.rtl;
          return Opacity(
            opacity: (1 - d.abs() * .35).clamp(0.0, 1.0),
            child: Transform(
              alignment: d > 0 ? (rtl ? Alignment.centerRight : Alignment.centerLeft) : (rtl ? Alignment.centerLeft : Alignment.centerRight),
              transform: perspective()
                ..rotateY((rtl ? 1 : -1) * d * turn)
                ..scaleByDouble(1 - d.abs() * .1, 1 - d.abs() * .1, 1, 1),
              child: child,
            ),
          );
        },
        child: child,
      );
}

/// Shrinks a little under the finger (with a light haptic) - for anything tappable that isn't a plain button.
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.onLongPress, this.scale = .96, this.haptic = true});
  final Widget child;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final double scale;
  final bool haptic;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;

  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: widget.onTap == null ? null : (_) => setState(() => _down = true),
        onTapCancel: () => setState(() => _down = false),
        onTapUp: (_) => setState(() => _down = false),
        onTap: widget.onTap == null
            ? null
            : () {
                if (widget.haptic) HapticFeedback.lightImpact();
                widget.onTap!();
              },
        onLongPress: widget.onLongPress,
        child: AnimatedScale(
          scale: _down ? widget.scale : 1,
          duration: const Duration(milliseconds: 120),
          curve: Curves.easeOut,
          child: widget.child,
        ),
      );
}

/// Comes in once: fades up from below with a slight 3D tilt, after [delay] (stagger lists with `index * 60ms`).
class Reveal extends StatefulWidget {
  const Reveal({super.key, required this.child, this.delay = Duration.zero, this.offset = 28, this.duration = const Duration(milliseconds: 520)});
  final Widget child;
  final Duration delay;
  final double offset;
  final Duration duration;

  @override
  State<Reveal> createState() => _RevealState();
}

class _RevealState extends State<Reveal> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: widget.duration);
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer(widget.delay, () {
      if (mounted) _c.forward();
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) {
          final v = Curves.easeOutCubic.transform(_c.value);
          return Opacity(
            opacity: v,
            child: Transform(
              alignment: Alignment.bottomCenter,
              transform: perspective()
                ..translateByDouble(0, (1 - v) * widget.offset, 0, 1)
                ..rotateX((1 - v) * .35),
              child: child,
            ),
          );
        },
        child: widget.child,
      );
}

/// Airport departures-board text: each letter flips through a few random ones before landing on its own,
/// left to right. Re-runs when the text changes.
class SplitFlap extends StatefulWidget {
  const SplitFlap(this.text, {super.key, required this.style, this.delay = Duration.zero, this.tile, this.tileColor});
  final String text;
  final TextStyle style;
  final Duration delay;
  final bool? tile; // draw each letter on its own dark tile (true by default for Latin text)
  final Color? tileColor;

  @override
  State<SplitFlap> createState() => _SplitFlapState();
}

class _SplitFlapState extends State<SplitFlap> with SingleTickerProviderStateMixin {
  static const _abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  late final AnimationController _c = AnimationController(vsync: this);
  final _rnd = math.Random();
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void didUpdateWidget(SplitFlap old) {
    super.didUpdateWidget(old);
    if (old.text != widget.text) _start();
  }

  void _start() {
    _t?.cancel();
    _c.duration = Duration(milliseconds: 380 + widget.text.length * 45);
    _c.value = 0;
    _t = Timer(widget.delay, () {
      if (mounted) _c.forward();
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    _c.dispose();
    super.dispose();
  }

  bool get _latin => !RegExp(r'[؀-ۿ]').hasMatch(widget.text);

  @override
  Widget build(BuildContext context) {
    // Arabic letters join, so they can't flip one by one: the whole word flips in instead.
    if (!_latin) {
      return AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Transform(
          alignment: Alignment.center,
          transform: perspective()..rotateX((1 - Curves.easeOutBack.transform(_c.value)) * math.pi / 2),
          child: Text(widget.text, style: widget.style),
        ),
      );
    }
    final tile = widget.tile ?? true;
    final chars = widget.text.characters.toList();
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) => Row(mainAxisSize: MainAxisSize.min, children: [
        for (var i = 0; i < chars.length; i++)
          _flapChar(chars[i], ((_c.value * (chars.length + 4)) - i).clamp(0.0, 4.0) / 4, tile),
      ]),
    );
  }

  Widget _flapChar(String ch, double t, bool tile) {
    final settled = t >= 1;
    final shown = settled || ch == ' ' ? ch : _abc[_rnd.nextInt(_abc.length)];
    final txt = Text(shown, style: widget.style);
    if (!tile) return txt;
    final fs = widget.style.fontSize ?? 14;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 1),
      padding: EdgeInsets.symmetric(horizontal: fs * .14, vertical: fs * .06),
      decoration: BoxDecoration(
        color: widget.tileColor ?? const Color(0xFF0A0F1C),
        borderRadius: BorderRadius.circular(fs * .18),
      ),
      child: Stack(alignment: Alignment.center, children: [
        txt,
        Positioned(left: 0, right: 0, child: Container(height: 1, color: Colors.black.withValues(alpha: .45))),
      ]),
    );
  }
}

/// A gentle endless bob (for the hero pass, the dock's plane, an empty state's emoji).
class Float extends StatefulWidget {
  const Float({super.key, required this.child, this.amount = 6, this.seconds = 4});
  final Widget child;
  final double amount;
  final double seconds;

  @override
  State<Float> createState() => _FloatState();
}

class _FloatState extends State<Float> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: Duration(milliseconds: (widget.seconds * 1000).round()))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) {
          final a = _c.value * 2 * math.pi;
          return Transform(
            alignment: Alignment.center,
            transform: perspective()
              ..translateByDouble(0, math.sin(a) * widget.amount, 0, 1)
              ..rotateX(math.cos(a) * .04)
              ..rotateY(math.sin(a) * .05),
            child: child,
          );
        },
        child: widget.child,
      );
}

/// Opens a screen with a 3D swing: the new page turns in from the side like a pass taken out of a wallet.
Route<T> passRoute<T>(Widget page) => PageRouteBuilder<T>(
      transitionDuration: const Duration(milliseconds: 520),
      reverseTransitionDuration: const Duration(milliseconds: 380),
      pageBuilder: (_, _, _) => page,
      transitionsBuilder: (context, a, _, child) {
        final v = Curves.easeOutCubic.transform(a.value);
        return Opacity(
          opacity: a.value.clamp(0, 1),
          child: Transform(
            alignment: Alignment.bottomCenter,
            transform: perspective()
              ..translateByDouble(0, (1 - v) * 80, 0, 1)
              ..rotateX((1 - v) * -.5),
            child: child,
          ),
        );
      },
    );
