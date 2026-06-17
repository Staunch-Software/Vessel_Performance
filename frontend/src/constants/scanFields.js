// ── Shared scan field catalogue ───────────────────────────────────────────────
export const SCAN_FIELDS = {
  Performance: [
    { key: 'Speed_Loss_pct',  label: 'Speed Loss (%)'      },
    { key: 'Power_Dev_pct',   label: 'Power Deviation (%)' },
    { key: 'SFOC_gkWh',       label: 'SFOC (g/kWh)'        },
    { key: 'VTI',             label: 'VTI'                 },
    { key: 'Est_Power_kW',    label: 'Est. Power (kW)'     },
  ],
  Fuel: [
    { key: 'ME_FOC_MT', label: 'ME FOC (mt)' },
    { key: 'AE_FOC_MT', label: 'AE FOC (mt)' },
  ],
  Navigation: [
    { key: 'SOG_kn',      label: 'SOG (kn)'       },
    { key: 'STW_kn',      label: 'STW (kn)'       },
    { key: 'Distance_nm', label: 'Distance (nm)'  },
    { key: 'Duration_h',  label: 'Duration (hrs)' },
    { key: 'Heading_deg', label: 'Heading (°)'    },
  ],
  Wind: [
    { key: 'True_Wind_Spd_ms',  label: 'True Wind Speed (m/s)' },
    { key: 'True_Wind_Dir_deg', label: 'True Wind Dir (°)'     },
    { key: 'Rel_Wind_Spd_ms',   label: 'Rel. Wind Speed (m/s)' },
  ],
  Sea: [
    { key: 'Sig_Wave_Ht_m',  label: 'Sig. Wave Ht (m)' },
    { key: 'Wave_Period_s',   label: 'Wave Period (s)'  },
    { key: 'Swell_Ht_m',     label: 'Swell Ht (m)'     },
    { key: 'Swell_Period_s',  label: 'Swell Period (s)' },
    { key: 'Current_Spd_kn', label: 'Current Spd (kn)' },
    { key: 'Water_Temp_C',   label: 'Water Temp (°C)'  },
    { key: 'Water_Depth_m',  label: 'Water Depth (m)'  },
  ],
  Engine: [
    { key: 'Shaft_Power_kW', label: 'Shaft Power (kW)' },
    { key: 'Shaft_RPM',      label: 'Shaft RPM'        },
    { key: 'AE_1_POWER_KW',  label: 'AE-1 Power (kW)'  },
    { key: 'AE_2_POWER_KW',  label: 'AE-2 Power (kW)'  },
    { key: 'AE_3_POWER_KW',  label: 'AE-3 Power (kW)'  },
  ],
  Draft: [
    { key: 'Mean_Draft_m',    label: 'Mean Draft (m)'    },
    { key: 'Draft_Fwd_m',     label: 'Draft Fwd (m)'     },
    { key: 'Draft_Aft_m',     label: 'Draft Aft (m)'     },
    { key: 'Trim_m',          label: 'Trim (m)'          },
    { key: 'Displacement_MT', label: 'Displacement (MT)' },
  ],
  Weather: [
    { key: 'P_wind_kW', label: 'P Wind (kW)' },
    { key: 'P_wave_kW', label: 'P Wave (kW)' },
  ],
}

export const CATEGORIES = Object.keys(SCAN_FIELDS)

export const OPERATORS = [
  { key: 'gt',      label: '> Greater than'     },
  { key: 'gte',     label: '≥ Greater or equal'  },
  { key: 'lt',      label: '< Less than'         },
  { key: 'lte',     label: '≤ Less or equal'     },
  { key: 'eq',      label: '= Equal to'          },
  { key: 'neq',     label: '≠ Not equal'         },
  { key: 'between', label: '↔ Between'            },
]

export const OP_SYM = {
  gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', neq: '≠', between: '↔',
}

// Context columns always shown in results tables
export const CONTEXT_COLS = [
  { key: 'vessel_name',  label: 'Vessel'    },
  { key: 'Date',         label: 'Date'      },
  { key: 'Voyage_No',    label: 'Voyage #'  },
  { key: 'Loading_Cond', label: 'L/B'       },
  { key: 'From_Port',    label: 'From Port' },
  { key: 'To_Port',      label: 'To Port'   },
]

/** Look up the human-readable label for a field key */
export function getFieldLabel(key) {
  for (const cat of CATEGORIES) {
    const f = SCAN_FIELDS[cat].find(f => f.key === key)
    if (f) return f.label
  }
  return key
}

/** Truncate an expression string for display in the manage-scans table */
export function condSummary(expression, _ignored = null, maxChars = 120) {
  if (!expression || typeof expression !== 'string') return '—'
  return expression.length > maxChars
    ? expression.slice(0, maxChars - 1) + '…'
    : expression
}
