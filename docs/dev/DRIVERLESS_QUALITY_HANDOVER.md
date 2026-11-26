# Driverless quality (Normal/Fine) for Android & Windows 11 — Handover

Task: make the Odroid CUPS queue offer the print-quality choice to driverless
clients (Android/Mopria, Windows 11 IPP, AirPrint), so "Fine" appears in the
standard print menu instead of only in the Brother-native BRResolution option.

Status: **done and verified on the live system.**

## 1. Why Fine was missing (verified, not assumed)

Android and Windows 11 print driverless over IPP and never read the PPD's
Brother-specific options. They only know the standard IPP `print-quality`
attribute (draft=3, normal=4, high=5) and `printer-resolution`.

CUPS maps `print-quality` to a `cupsPrintQuality` PPD option
(`Mapping cupsPrintQuality=%s to print-quality=%d` in cupsd). That option was
**not present** in our PPD, so CUPS could not translate it. The queue therefore
advertised `print-quality-supported = normal` only, and `printer-resolution`
fell back to a generic 300 dpi.

Confirmed with a dummy filter that logged its argv: a job carrying
`print-quality=5` reached the filter as `cupsPrintQuality=High` **only after**
the PPD defined `*cupsPrintQuality`. Without it, neither attribute reached the
filter and `BRResolution` (which driverless clients never send) stayed at its
default.

## 2. What was changed

**PPD** `hl3040cn/cups/brhl3040cn.ppd` — added two standard groups after
`*CloseUI: *BRResolution`:

```
*OpenUI *cupsPrintQuality/Print Quality: PickOne
*DefaultcupsPrintQuality: High
*cupsPrintQuality Draft/Draft (fast): ...
*cupsPrintQuality Normal/Normal (600 x 600dpi): ...
*cupsPrintQuality High/Fine (2400 dpi class): ...
*CloseUI: *cupsPrintQuality

*OpenUI *Resolution/Output Resolution: PickOne
*DefaultResolution: 600x2400dpi
*Resolution 600dpi/Normal (600 x 600dpi): ...
*Resolution 600x2400dpi/Fine (2400 dpi class): ...
*CloseUI: *Resolution
```

**Filter** `hl3040cn/src/settings.py` — `PrintSettings.from_cups_options` now
maps the standard attributes to `Resolution`. The **job's** options are
evaluated before the PPD defaults, because the PPD always supplies a
`BRResolution` default that would otherwise mask the client's choice. Priority:
`BRResolution` > `cupsPrintQuality` > `print-quality` > `Resolution` >
`printer-resolution`.

**Test** `hl3040cn/src/test_consistency.py` — accepts the two new PPD groups
and pins the mapping (23 tests, all pass).

## 3. Result

Live queue now advertises (ipptool Get-Printer-Attributes, localhost and LAN IP):

```
print-quality-supported (1setOf enum) = draft,normal,high
printer-resolution-supported (1setOf resolution) = 600dpi,600x2400dpi
printer-resolution-default (resolution) = 600x2400dpi
```

Android/Windows show a quality selector with three entries; "High" selects Fine.
End-to-end through CUPS with the real filter: `print-quality=5` produced a
4502-byte Fine XL2HB file, `print-quality=4` a 4434-byte Normal one.

## 4. Notes / caveats

* `print-quality-default` stays `normal` in the IPP attributes even with
  `*DefaultcupsPrintQuality: High`. This is CUPS behaviour, not something the
  PPD controls; a client that sends nothing gets the filter's own default
  (Fine, per the current `Resolution` default). A client that explicitly sends
  normal/4 gets Normal.
* The default `Resolution` in `PrintSettings` is `Fine` (changed by a parallel
  agent). That makes `test_toner_save.test_black_page_changes` fail, because
  Fine mode makes toner-save a no-op on a solid black page. That failure is
  **not** from this change (it only touches `from_cups_options`); it belongs to
  the Fine-default decision and should be resolved there.
* Do not re-add `*OpenUI *Duplex` — the HL-3040CN has no duplex unit, and
  `test_consistency.PpCapabilityTest` enforces this.
* Installed copies: `/usr/share/cups/model/brhl3040cn.ppd`,
  `/etc/cups/ppd/Brother_HL-3040CN.ppd`,
  `/usr/local/lib/brhl3040cn/settings.py`. Backups of the previous versions are
  in `backup-quality-<timestamp>/`.

## 5. Follow-up (2026-10-26, later) — Fine is now the advertised default

The open item above is resolved.

**`print-quality-default` was `normal`, so driverless clients pre-selected
Normal.** `*DefaultcupsPrintQuality: High` in the PPD does not drive the IPP
`print-quality-default` attribute — CUPS keeps that at `normal`. Verified with a
throwaway queue built from the repo PPD: advertised default stayed `normal`.

**Lever (verified, not assumed):** a queue option `print-quality-default=5`
sets the advertised default to `high` **and** injects `print-quality=5
cupsPrintQuality=High` into every no-option job. Confirmed with a temporary
logging filter in `/usr/lib/cups/filter/` (AppArmor only lets filters run from
there — a filter in `/mnt/ssd` fails with `execv failed: Permission denied`):

| job | argv seen by the filter |
|---|---|
| no option, queue without the setting | *(no quality attribute at all)* |
| no option, queue with `print-quality-default=5` | `print-quality=5 … cupsPrintQuality=High` |
| explicit `print-quality=4`, queue default high | `print-quality=4 … cupsPrintQuality=Normal` |

So an explicit client choice still wins; only the default changes.

**Applied:** `/usr/sbin/lpadmin -p Brother_HL-3040CN -o print-quality-default=5`.
Persisted as `Option print-quality 5` in `/etc/cups/printers.conf`. The queue now
advertises `print-quality-default = high`. Made durable in
`hl3040cn/cups/install.sh` so a reinstall keeps it.

**`test_toner_save` failure resolved.** The test was written before the
Fine-default change; its `render()` helper never pinned a resolution, so once
`PrintSettings.resolution` defaulted to Fine it silently exercised the known-open
Fine path (Fine makes toner-save a no-op on a solid black page — see
FINE_HANDOVER.md). Fix: pin `Resolution.NORMAL` in the helper, which is what the
`-TS` tables and the assertion describe. Full suite green again
(`test_consistency`, `test_dither_tables`, `test_gray_replace`, `test_toner_save`,
`test_fine_mode`, `test_a4_geometry`).

**Still open:** Fine mode is not byte-identical to Brother's filter — owned by
the Fine-quantiser agent, see FINE_HANDOVER.md.
