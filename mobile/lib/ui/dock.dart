import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';

/// The floating dock: Home, My trip, (the plane - the chat), Events, Passport. A glowing pill slides under the
/// open tab; the plane in the middle spins its propeller-glow while Dalili is planning; dots mark what's new.
class Dock extends StatelessWidget {
  const Dock({super.key, required this.state});
  final AppState state;

  static const _items = [
    (Tabs.home, Icons.home_outlined, Icons.home_rounded, 'tabHome'),
    (Tabs.trip, Icons.confirmation_number_outlined, Icons.confirmation_number_rounded, 'tabTrip'),
    (Tabs.chat, null, null, 'tabChat'),
    (Tabs.events, Icons.local_activity_outlined, Icons.local_activity_rounded, 'tabEvents'),
    (Tabs.me, Icons.badge_outlined, Icons.badge_rounded, 'tabMe'),
  ];

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.viewPaddingOf(context).bottom;
    final dark = context.dark;
    return Padding(
      padding: EdgeInsets.fromLTRB(14, 0, 14, math.max(10, bottom)),
      child: SizedBox(
        height: 74,
        child: Stack(clipBehavior: Clip.none, children: [
          Positioned.fill(
            top: 8,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(26),
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
                child: Container(
                  decoration: BoxDecoration(
                    color: dark ? const Color(0xCC0D1424) : Colors.white.withValues(alpha: .82),
                    borderRadius: BorderRadius.circular(26),
                    border: Border.all(color: dark ? Colors.white.withValues(alpha: .08) : const Color(0x1A1C3460)),
                  ),
                ),
              ),
            ),
          ),
          Positioned.fill(
            top: 8,
            child: LayoutBuilder(builder: (context, c) {
              final slot = c.maxWidth / 5;
              final i = state.tab;
              return Stack(children: [
                if (i != Tabs.chat)
                  AnimatedPositionedDirectional(
                    duration: const Duration(milliseconds: 420),
                    curve: Curves.easeOutBack,
                    start: slot * i + slot * .16,
                    width: slot * .68,
                    top: 7,
                    height: 36,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: DC.teal.withValues(alpha: dark ? .16 : .2),
                        borderRadius: BorderRadius.circular(14),
                        boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: .25), blurRadius: 16)],
                      ),
                    ),
                  ),
                Row(children: [
                  for (final (tab, icon, on, label) in _items)
                    Expanded(
                      child: tab == Tabs.chat
                          ? const SizedBox()
                          : _DockButton(
                              icon: state.tab == tab ? on! : icon!,
                              label: tr(label),
                              active: state.tab == tab,
                              dot: state.unread.contains(tab),
                              onTap: () => _go(tab),
                            ),
                    ),
                ]),
              ]);
            }),
          ),
          Align(
            alignment: Alignment.topCenter,
            child: _PlaneButton(
              busy: state.busy,
              active: state.tab == Tabs.chat,
              dot: state.unread.contains(Tabs.chat),
              onTap: () => _go(Tabs.chat),
            ),
          ),
        ]),
      ),
    );
  }

  void _go(int tab) {
    if (state.tab == tab) return;
    HapticFeedback.selectionClick();
    state.goTab(tab);
    if (tab == Tabs.home || tab == Tabs.trip) state.refreshHome();
  }
}

class _DockButton extends StatelessWidget {
  const _DockButton({required this.icon, required this.label, required this.active, required this.dot, required this.onTap});
  final IconData icon;
  final String label;
  final bool active;
  final bool dot;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = active ? (context.dark ? DC.teal : DC.tealDeep) : context.muted;
    return Semantics(
      button: true,
      selected: active,
      label: label,
      child: InkResponse(
        onTap: onTap,
        radius: 34,
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          Stack(clipBehavior: Clip.none, children: [
            AnimatedScale(
              scale: active ? 1.12 : 1,
              duration: const Duration(milliseconds: 300),
              curve: Curves.easeOutBack,
              child: Icon(icon, color: color, size: 24),
            ),
            if (dot)
              PositionedDirectional(
                top: -2,
                end: -4,
                child: Container(
                  width: 9,
                  height: 9,
                  decoration: BoxDecoration(color: DC.rose, shape: BoxShape.circle, border: Border.all(color: context.card, width: 1.5)),
                ),
              ),
          ]),
          const SizedBox(height: 3),
          Text(label, maxLines: 1, overflow: TextOverflow.fade, softWrap: false,
              style: TextStyle(fontSize: 10.5, fontWeight: active ? FontWeight.w800 : FontWeight.w600, color: color)),
        ]),
      ),
    );
  }
}

/// The raised plane in the middle of the dock (the chat). While a plan is being made a ring of light circles it.
class _PlaneButton extends StatefulWidget {
  const _PlaneButton({required this.busy, required this.active, required this.dot, required this.onTap});
  final bool busy;
  final bool active;
  final bool dot;
  final VoidCallback onTap;

  @override
  State<_PlaneButton> createState() => _PlaneButtonState();
}

class _PlaneButtonState extends State<_PlaneButton> with SingleTickerProviderStateMixin {
  late final AnimationController _spin = AnimationController(vsync: this, duration: const Duration(milliseconds: 1400));

  @override
  void initState() {
    super.initState();
    if (widget.busy) _spin.repeat();
  }

  @override
  void didUpdateWidget(_PlaneButton old) {
    super.didUpdateWidget(old);
    if (widget.busy && !_spin.isAnimating) _spin.repeat();
    if (!widget.busy && _spin.isAnimating) _spin.stop();
  }

  @override
  void dispose() {
    _spin.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: tr('tabChat'),
        child: GestureDetector(
          onTap: widget.onTap,
          child: SizedBox(
            width: 64,
            height: 64,
            child: Stack(alignment: Alignment.center, clipBehavior: Clip.none, children: [
              if (widget.busy)
                AnimatedBuilder(
                  animation: _spin,
                  builder: (_, _) => Transform.rotate(
                    angle: _spin.value * 2 * math.pi,
                    child: Container(
                      width: 64,
                      height: 64,
                      decoration: const BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: SweepGradient(colors: [Color(0x003DE0D0), DC.teal, Color(0x0036B7FF)]),
                      ),
                    ),
                  ),
                ),
              AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                width: widget.active ? 58 : 54,
                height: widget.active ? 58 : 54,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: DC.brand,
                  border: Border.all(color: context.dark ? DC.night : Colors.white, width: 3),
                  boxShadow: [BoxShadow(color: DC.teal.withValues(alpha: widget.active ? .55 : .35), blurRadius: widget.active ? 24 : 16, offset: const Offset(0, 6))],
                ),
                child: Transform.rotate(
                  angle: isArabic ? -math.pi / 4 : math.pi / 4, // flight_rounded points up: tilt it toward the reading direction
                  child: const Icon(Icons.flight_rounded, color: DC.onBrand, size: 26),
                ),
              ),
              if (widget.dot)
                Positioned(
                  top: 4,
                  right: 6,
                  child: Container(
                    width: 11,
                    height: 11,
                    decoration: BoxDecoration(color: DC.rose, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)),
                  ),
                ),
            ]),
          ),
        ),
      );
}
