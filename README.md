# Axiro PA Testbench

A Python/Tkinter desktop application for automated Power Amplifier (PA) characterization. Connects to bench instruments over GPIB/VISA, runs scripted sweep plans, and logs full RF + DC data to CSV for analysis.

---

## Features

- **Device Manager** — Connect/disconnect GPIB/USB instruments by VISA address with custom aliases and per-device detail panel
- **Sweep Plan** — Drag-and-drop style step sequencer with a full properties panel per step
- **Run Engine** — Multithreaded execution engine with live step highlighting, stop-on-demand, and auto CSV export
- **Power Sweep** — Sweeps Pin from SG, reads Pout from SA, and optionally logs Vdd/Idd/PAE/DE from a drain PSU channel per point
- **Ramp Editor** — Build gate/drain voltage ramp profiles used by Ramp Up/Down steps
- **Results Viewer** — Auto-loads the latest run CSV, interactive charts (Gain, PAE, DE, Pout vs Pin), filter by command, group by freq/Vdd
- **Power Supply Tab** — Manual PSU control with live polling
- **Signal Generator Tab** — Manual SG control, instrument filesystem browser (via `MMEM:CAT?` over VISA), and PC-to-instrument waveform upload
- **Spectrum Analyzer Tab** — Manual SA control with live trace
- **DMM Tab** — Live voltage/current readback
- **Sequencer Tab** — Legacy sequencer for quick ad-hoc steps

---

## Supported Instruments

| Instrument | Driver File | Channels |
|---|---|---|
| Keysight E36234A / E36233A PSU | `drivers/keysight_e36xx.py` | 2–4 |
| Agilent E3648A PSU | `drivers/agilent_e3648a.py` | 2 |
| HP 6633B PSU | `drivers/hp_6633b.py` | 1 |
| Rohde & Schwarz SMBV100B SG | `drivers/rs_smbv100b.py` | — |
| Keysight PSG/MXG/EXG SG | Registry key matched on `PSG`, `MXG`, `EXG` | — |
| Keysight N9030A / PXA / MXA SA | Registry key matched on `N9030`, `PXA`, `MXA`, `EXA` | — |
| Keysight 34465A / 34461A DMM | Registry key matched on `34465`, `34461` | — |

---

## Project Structure

```
PA_TESTBENCH/
├── main.py                       # App entry point, tab wiring
├── run_engine.py                 # Threaded sweep execution engine
├── instrument_aliases.json       # Saved instrument alias map
├── drivers/
│   ├── keysight_e36xx.py         # Keysight E36233A / E36234A PSU (rewritten)
│   ├── agilent_e3648a.py
│   ├── hp_6633b.py
│   ├── rs_smbv100b.py            # R&S SMBV100B signal generator
│   └── ...
├── tabs/
│   ├── device_info_tab.py        # Device Manager (connect, alias, self-test, reset)
│   ├── sweep_plan_tab.py         # Sweep plan builder + run control
│   ├── results_viewer_tab.py     # CSV viewer + charts
│   ├── ramp_editor_tab.py        # Ramp profile editor
│   ├── power_supply_tab.py       # PSU manual control
│   ├── signal_generator_tab.py   # SG control + waveform management
│   ├── spectrum_analyzer_tab.py
│   ├── dmm_tab.py
│   └── sequencer_tab.py
└── utils/
    ├── visa_manager.py           # Shared pyvisa ResourceManager
    ├── visa_helper.py            # load_driver() dispatcher
    ├── ui_theme.py               # App-wide colours, stat cards, treeview styles
    ├── freq_entry.py             # Frequency entry widget with unit selector
    └── logger.py                 # App-wide logger
```

---

## Installation

**Requirements:**
- Python 3.10+
- NI-VISA or Keysight IO Libraries installed on the host machine

```bash
pip install pyvisa pyvisa-py matplotlib
```

> If using NI-VISA backend (recommended for GPIB), install [NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) separately.

**Run:**
```bash
python main.py
```

---

## Device Manager

The first tab lists all configured instruments. Click **Connect All** to attempt VISA connections to every entry.
Once connected, each row shows the IDN response, loaded driver class, and status.
Select any row to see full details and per-device actions (Reconnect, Self-Test, Reset, Edit Alias) in the right-hand panel.

> The numeric summary cards (total / connected / errors) have been removed from the top of this tab for a cleaner layout. Status is visible directly in the table and bottom status bar.

---

## Signal Generator — Waveform Management

The **Waveform Management** panel on the Signal Generator tab has three sections:

### Upload from This PC
Transfer a waveform file from your local machine to the instrument over VISA using `MMEM:DATA` binary block transfer.

1. Click **Browse…** to pick a `.wv`, `.iq`, `.bin`, or `.csv` file from your PC.
2. Set the **Destination folder on instrument** (default: `/var/user/waveform`).
3. Click **Upload to Instrument** — the file is transferred and the instrument file tree refreshes automatically.

### Browse Instrument Files (via VISA)
Browse the instrument's internal filesystem directly over SCPI using `MMEM:CAT?` — no network share or USB stick needed.

- Select a root path from the dropdown (`/var/user`, `/user`, `/users`, `/var/user/waveform`) or type any custom path.
- Click **↺ Browse** to load the directory listing from the instrument.
- Folders expand lazily on click; only waveform files (`.wv`, `.iq`, `.bin`, `.csv`) are shown alongside all subdirectories.
- **Double-click** a file to select it, then click **Set as Active Waveform** to send `SOUR:BB:ARB:WAV:SEL` with the full instrument path and enable ARB mode.

### Waveforms on Device (ARB Catalogue)
Queries `SOUR:BB:ARB:WAV:CAT?` (with `MMEM:CAT?` fallback) to list waveforms already registered in the ARB engine.
Use **Select Waveform** to activate one, or **Delete Waveform** to remove it from the instrument.

---

## Keysight E36xx Power Supply Driver

The `drivers/keysight_e36xx.py` driver covers the **E36233A** (2-ch) and **E36234A** (4-ch) families.
It was rewritten from scratch to address communication reliability issues:

| Fix | Detail |
|---|---|
| Explicit terminators | `read_termination = "\n"`, `write_termination = "\n"` set on open |
| Connect flush | `*CLS` + `*RST` on every connect with a 300 ms settle delay |
| Inter-command delay | 20 ms between every write/query to prevent buffer overruns |
| Channel select | Uses `INST:NSEL {n}` (1-based numeric) — correct for E362xx firmware |
| Error queue drain | `check_errors()` reads `SYST:ERR?` up to 20 times and logs non-zero entries |
| Debug mode | Pass `debug=True` on instantiation to auto-call `check_errors()` after every write |
| OVP / OCP | Uses `VOLT:PROT` and `CURR:PROT` (colon form, not `VOLT:PROT:LEV`) |

```python
from drivers.keysight_e36xx import KeysightE36xxSupply

psu = KeysightE36xxSupply(
    visa_address="USB0::0x2A8D::0x3402::MY61002290::INSTR",
    name="E36234A",
    channels=4,
    debug=True,   # logs SCPI errors after every write
)
psu.connect()
psu.set_voltage(1, 28.0)
psu.set_current(1, 2.0)
psu.output_on(1, True)
print(psu.measure_all(1))   # {'volt': 28.0, 'curr': 0.45}
psu.close()
```

---

## Sweep Plan Steps

### Biasing
| Step | Description |
|---|---|
| Set Gate Bias | Set gate channel voltage/current + OCP/OVP |
| Set Drain Bias | Set drain channel voltage/current + optional Idq targeting |
| Ramp Up / Ramp Down | Execute Ramp Editor profile or manual override |
| Output ON / OFF | Enable or disable a PSU channel output |
| Bias Sweep | Step a PSU channel voltage over a range |
| Idq Optimize | Walk gate voltage until drain current hits target |

### Measurement
| Step | Description |
|---|---|
| Power Sweep | Sweep Pin (SG), read Pout (SA), log Vdd/Idd/PAE/DE (PSU) per point |
| Perform Measurement | Single SA acquisition with optional label |
| Gain Compression | Find P1dB (or PNdB) compression point |
| ACPR | Adjacent Channel Power Ratio measurement |
| Harmonics | 2nd/3rd harmonic levels relative to fundamental |
| PAE Sweep | Power sweep with PAE tracking |
| Frequency Sweep | Outer frequency loop with inner power sweep |
| Save Results | Write current session to CSV at this point in the plan |

### Flow Control
| Step | Description |
|---|---|
| Group | Visual grouping only — no runtime effect |
| Loop | Repeat enclosed steps N times |
| Wait | Pause execution for N seconds |
| Message | Log a text message to the run CSV |
| Conditional Abort | Abort run if a PSU channel current exceeds threshold |

### SCPI
| Step | Description |
|---|---|
| SCPI Command | Send a raw SCPI write to any connected instrument |
| SCPI Poll Loop | Repeatedly query until response matches expected or timeout |

---

## CSV Output

After every run, results are written to `results/sweep_YYYYMMDD_HHMMSS.csv` and auto-loaded in the Results tab.

**Power Sweep columns:**

| Column | Description |
|---|---|
| `command` | Always `POWER_SWEEP` |
| `freq_ghz` | Frequency set on the SG |
| `pin_dbm` | Input power (set on SG) |
| `pout_dbm` | Output power (measured by SA) |
| `gain_db` | Pout - Pin |
| `vdd_v` | Drain voltage (measured from PSU) |
| `idd_a` | Drain current (measured from PSU) |
| `pdc_w` | DC power = Vdd × Idd |
| `de_pct` | Drain efficiency = (Pout_W / Pdc_W) × 100 |
| `pae_pct` | PAE = ((Pout_W - Pin_W) / Pdc_W) × 100 |
| `timestamp` | ISO 8601 timestamp per point |

> `vdd_v`, `idd_a`, `pdc_w`, `de_pct`, `pae_pct` are only logged when a **Drain Channel** is selected in the Power Sweep step properties.

---

## Plan Files

Plans are saved as `.axplan` (JSON) files and can be reopened, edited, and re-run.

```json
{
  "title": "My PA Test",
  "version": "1.0",
  "steps": [
    { "type": "set_drain_bias", "display_name": "Set Drain Bias", "params": { "channel": "HP_6633B CH1", "voltage": 28.0, "ocp": 2.0 } },
    { "type": "power_sweep",    "display_name": "Power Sweep",    "params": { "start_dbm": -20, "stop_dbm": 10, "step_db": 1.0, "dwell_ms": 200, "drain_channel": "HP_6633B CH1", "freq_ghz": "2.4" } }
  ]
}
```

---

## License

Internal use — Axiro / Raj Patel. Not for public distribution.
