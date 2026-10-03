# Wargame d7e8d138

Created: 2026-10-03T11:53:45Z
Status: done
Model: Qwen/Qwen2.5-72B-Instruct
Base branch: main
Base loss: 0.0%
Rounds: 6
Final loss vs base: 39.0 percentage points

Scores use gameplay assumptions; they are not calibrated production forecasts.

Cumulative loss: 188.1 percentage-point rounds
Average loss: 31.4%
Priority objectives held: False

## 1. Round 0 · INJECT

Exercise rules: 14 credits; protect priority programmes above 80%

Rationale: Finite capacity, delayed recovery, two-round stocks and partial hardening.

```json
[
  {
    "action": "game_init",
    "args": {
      "rounds": 6,
      "seed": 7
    }
  }
]
```

Loss: 0.0% total; 0.0 points vs base
Deep network: 0.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 14,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 100.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 100.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 100.0,
      "threshold_pct": 80
    }
  ],
  "round": 0,
  "event_active": false,
  "cost": 0,
  "ready_round": 0,
  "cumulative_loss": 0.0,
  "planning": null,
  "alternatives": []
}
```
Branch: main → 968
Timing: LLM 0 ms; DB 1526.5 ms
Fallback: no
Map arcs: 0

## 2. Round 0 · BLUE

Harden port USLAX (Port of Los Angeles)

Rationale: Harden Port of Los Angeles to prevent a significant potential loss and protect critical supply lines.

```json
[
  {
    "action": "game_order",
    "args": {
      "action": "harden",
      "args": {
        "port_id": "USLAX"
      }
    }
  }
]
```

Loss: 0.0% total; 0.0 points vs base
Deep network: 0.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 11,
  "budget_total": 14,
  "pending": [
    {
      "cost": 3,
      "due": 1,
      "step": {
        "action": "harden",
        "args": {
          "port_id": "USLAX"
        }
      }
    }
  ],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 100.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 100.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 100.0,
      "threshold_pct": 80
    }
  ],
  "round": 0,
  "event_active": false,
  "cost": 3,
  "ready_round": 1,
  "cumulative_loss": 0.0,
  "planning": {
    "branches_evaluated": 4,
    "response": "Close port USHOU",
    "immediate_loss_pct": 0.0,
    "future_loss_pct": 25.5,
    "average_loss_pct": 17.0,
    "horizon_round": 2,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 40.0,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 70.6,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 70.6,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": []
}
```
Branch: 968 → 973
Timing: LLM 6252.9 ms; DB 14028.1 ms
Fallback: no
Map targets: Port of Los Angeles (port, 33.73, -118.26)
Map arcs: 0

## 3. Round 0 · INJECT

Ready: harden {'port_id': 'USLAX'}

Rationale: Ready: harden {'port_id': 'USLAX'}

```json
[
  {
    "action": "game_tick",
    "args": {
      "round": 1
    }
  }
]
```

Loss: 0.0% total; 0.0 points vs base
Deep network: 0.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 11,
  "budget_total": 14,
  "pending": [],
  "completed": [
    "Ready: harden {'port_id': 'USLAX'}"
  ],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 100.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 100.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 100.0,
      "threshold_pct": 80
    }
  ],
  "round": 1,
  "event_active": false,
  "cost": 0,
  "ready_round": 0,
  "cumulative_loss": 0.0,
  "planning": null,
  "alternatives": [
    {
      "label": "Harden port USLAX",
      "cost": 3,
      "ready_round": 1,
      "planning": {
        "branches_evaluated": 4,
        "response": "Close port USHOU",
        "immediate_loss_pct": 0.0,
        "future_loss_pct": 25.5,
        "average_loss_pct": 17.0,
        "horizon_round": 2,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 40.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 70.6,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 973 → 974
Timing: LLM 0 ms; DB 280.7 ms
Fallback: no
Map arcs: 0

## 4. Round 1 · RED

Close port USHOU (Port of Houston)

Rationale: Closing the Port of Houston will immediately disrupt a significant number of exporters and create lasting congestion, which is harder for Blue to quickly mitigate.

```json
[
  {
    "action": "close_port",
    "args": {
      "port_id": "USHOU"
    }
  }
]
```

Loss: 25.5% total; 25.5 points vs base
Deep network: 34.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 11,
  "budget_total": 14,
  "pending": [],
  "completed": [
    "Ready: harden {'port_id': 'USLAX'}"
  ],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 40.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 70.6,
      "threshold_pct": 80
    }
  ],
  "round": 1,
  "event_active": false,
  "cost": 0,
  "ready_round": 1,
  "cumulative_loss": 12.8,
  "planning": {
    "branches_evaluated": 4,
    "response": "Reroute exports away from port USHOU",
    "immediate_loss_pct": 25.5,
    "future_loss_pct": 10.7,
    "average_loss_pct": 14.4,
    "horizon_round": 3,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 74.7,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 87.9,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 87.9,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "Block the Dover Strait",
      "cost": 0,
      "ready_round": 1,
      "planning": {
        "branches_evaluated": 4,
        "response": "Harden facility FAC04229",
        "immediate_loss_pct": 20.8,
        "future_loss_pct": 20.8,
        "average_loss_pct": 20.8,
        "horizon_round": 3,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 75.5,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 75.5,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    },
    {
      "label": "Outage at facility FAC04229",
      "cost": 0,
      "ready_round": 1,
      "planning": {
        "branches_evaluated": 4,
        "response": "Harden port GBFXT",
        "immediate_loss_pct": 17.7,
        "future_loss_pct": 17.7,
        "average_loss_pct": 17.7,
        "horizon_round": 3,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 0.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 100.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 100.0,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 974 → 987
Timing: LLM 6034.7 ms; DB 38792.5 ms
Fallback: no
Map targets: Port of Houston (port, 29.73, -95.27)
Map arcs: 71

## 5. Round 1 · BLUE

Reroute exports away from port USHOU (Port of Houston)

Rationale: Rerouting exports from the closed Port of Houston will immediately reduce the current capability loss by spreading the burden across other open ports.

```json
[
  {
    "action": "game_order",
    "args": {
      "action": "reroute_exports",
      "args": {
        "port_id": "USHOU"
      }
    }
  }
]
```

Loss: 10.7% total; 10.7 points vs base
Deep network: 14.3%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 9,
  "budget_total": 14,
  "pending": [],
  "completed": [
    "Ready: harden {'port_id': 'USLAX'}"
  ],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 74.7,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 87.9,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 87.9,
      "threshold_pct": 80
    }
  ],
  "round": 1,
  "event_active": false,
  "cost": 2,
  "ready_round": 1,
  "cumulative_loss": 18.1,
  "planning": {
    "branches_evaluated": 4,
    "response": "Outage at facility FAC04229",
    "immediate_loss_pct": 10.7,
    "future_loss_pct": 23.9,
    "average_loss_pct": 19.5,
    "horizon_round": 3,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 0.0,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 87.9,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 87.9,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "Harden facility FAC04299",
      "cost": 3,
      "ready_round": 2,
      "planning": {
        "branches_evaluated": 4,
        "response": "Outage at facility FAC04229",
        "immediate_loss_pct": 25.5,
        "future_loss_pct": 32.6,
        "average_loss_pct": 30.2,
        "horizon_round": 3,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 0.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 70.6,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 987 → 996
Timing: LLM 4575.9 ms; DB 17738.8 ms
Fallback: no
Map targets: Port of Houston (port, 29.73, -95.27)
Map arcs: 71

## 6. Round 1 · INJECT

Round 2: recovery clock advanced

Rationale: Round 2: recovery clock advanced

```json
[
  {
    "action": "game_tick",
    "args": {
      "round": 2
    }
  }
]
```

Loss: 10.7% total; 10.7 points vs base
Deep network: 14.3%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 9,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 74.7,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 87.9,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 87.9,
      "threshold_pct": 80
    }
  ],
  "round": 2,
  "event_active": false,
  "cost": 0,
  "ready_round": 1,
  "cumulative_loss": 18.1,
  "planning": null,
  "alternatives": [
    {
      "label": "Reroute exports away from port USHOU",
      "cost": 2,
      "ready_round": 1,
      "planning": {
        "branches_evaluated": 4,
        "response": "Outage at facility FAC04229",
        "immediate_loss_pct": 10.7,
        "future_loss_pct": 23.9,
        "average_loss_pct": 19.5,
        "horizon_round": 3,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 0.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 87.9,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 87.9,
            "threshold_pct": 80
          }
        ]
      }
    },
    {
      "label": "Harden facility FAC04299",
      "cost": 3,
      "ready_round": 2,
      "planning": {
        "branches_evaluated": 4,
        "response": "Outage at facility FAC04229",
        "immediate_loss_pct": 25.5,
        "future_loss_pct": 32.6,
        "average_loss_pct": 30.2,
        "horizon_round": 3,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 0.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 70.6,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 996 → 997
Timing: LLM 0 ms; DB 485.0 ms
Fallback: no
Map arcs: 0

## 7. Round 2 · RED

Outage at facility FAC04229 (Norvex Isard Defence Systems Inc. - Boston)

Rationale: Targeting a single point of failure with high estimated gain and long-term impact on critical programmes is most effective.

```json
[
  {
    "action": "facility_outage",
    "args": {
      "facility_id": "FAC04229"
    }
  }
]
```

Loss: 23.9% total; 23.9 points vs base
Deep network: 31.9%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 9,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 87.9,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 87.9,
      "threshold_pct": 80
    }
  ],
  "round": 2,
  "event_active": false,
  "cost": 0,
  "ready_round": 2,
  "cumulative_loss": 30.1,
  "planning": {
    "branches_evaluated": 4,
    "response": "Harden port GBFXT",
    "immediate_loss_pct": 23.9,
    "future_loss_pct": 29.0,
    "average_loss_pct": 25.2,
    "horizon_round": 4,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 0.0,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 80.5,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 80.5,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "Block the Dover Strait",
      "cost": 0,
      "ready_round": 2,
      "planning": {
        "branches_evaluated": 4,
        "response": "Harden facility FAC04229",
        "immediate_loss_pct": 23.2,
        "future_loss_pct": 27.4,
        "average_loss_pct": 24.2,
        "horizon_round": 4,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 51.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 73.9,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    },
    {
      "label": "CHN export controls on MAT00017",
      "cost": 0,
      "ready_round": 2,
      "planning": {
        "branches_evaluated": 4,
        "response": "Harden port USNYC",
        "immediate_loss_pct": 11.5,
        "future_loss_pct": 18.4,
        "average_loss_pct": 13.2,
        "horizon_round": 4,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 59.7,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 80.5,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 80.5,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 997 → 1010
Timing: LLM 4311.1 ms; DB 38892.1 ms
Fallback: no
Map targets: Norvex Isard Defence Systems Inc. - Boston (facility, 42.399415, -71.030567)
Map arcs: 0

## 8. Round 2 · BLUE

Replace the production of facility FAC04229 (Norvex Isard Defence Systems Inc. - Boston)

Rationale: Replacing the facility will recover the most immediate loss and ensure long-term resilience, despite the higher cost.

```json
[
  {
    "action": "game_order",
    "args": {
      "action": "replace_facility",
      "args": {
        "facility_id": "FAC04229"
      }
    }
  }
]
```

Loss: 23.9% total; 23.9 points vs base
Deep network: 31.9%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 4,
  "budget_total": 14,
  "pending": [
    {
      "cost": 5,
      "due": 4,
      "step": {
        "action": "replace_facility",
        "args": {
          "facility_id": "FAC04229"
        }
      }
    }
  ],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 87.9,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 87.9,
      "threshold_pct": 80
    }
  ],
  "round": 2,
  "event_active": false,
  "cost": 5,
  "ready_round": 4,
  "cumulative_loss": 42.0,
  "planning": {
    "branches_evaluated": 4,
    "response": "Block the Dover Strait",
    "immediate_loss_pct": 23.9,
    "future_loss_pct": 31.4,
    "average_loss_pct": 29.9,
    "horizon_round": 4,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 28.3,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 73.9,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 65.0,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "Qualify a second source for PLT00003",
      "cost": 3,
      "ready_round": 4,
      "planning": {
        "branches_evaluated": 4,
        "response": "Block the Dover Strait",
        "immediate_loss_pct": 23.9,
        "future_loss_pct": 31.1,
        "average_loss_pct": 29.8,
        "horizon_round": 4,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 30.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 73.9,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    },
    {
      "label": "Harden port GBFXT",
      "cost": 3,
      "ready_round": 3,
      "planning": {
        "branches_evaluated": 4,
        "response": "Block the Dover Strait",
        "immediate_loss_pct": 23.9,
        "future_loss_pct": 36.4,
        "average_loss_pct": 31.6,
        "horizon_round": 4,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 0.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 73.9,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1010 → 1023
Timing: LLM 13756.0 ms; DB 36515.6 ms
Fallback: no
Map targets: Norvex Isard Defence Systems Inc. - Boston (facility, 42.399415, -71.030567)
Map arcs: 0

## 9. Round 2 · INJECT

Round 3: recovery clock advanced

Rationale: Round 3: recovery clock advanced

```json
[
  {
    "action": "game_tick",
    "args": {
      "round": 3
    }
  }
]
```

Loss: 23.9% total; 23.9 points vs base
Deep network: 31.9%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 4,
  "budget_total": 14,
  "pending": [
    {
      "cost": 5,
      "due": 4,
      "step": {
        "action": "replace_facility",
        "args": {
          "facility_id": "FAC04229"
        }
      }
    }
  ],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 87.9,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 87.9,
      "threshold_pct": 80
    }
  ],
  "round": 3,
  "event_active": false,
  "cost": 0,
  "ready_round": 2,
  "cumulative_loss": 42.0,
  "planning": null,
  "alternatives": [
    {
      "label": "Qualify a second source for PLT00003",
      "cost": 3,
      "ready_round": 4,
      "planning": {
        "branches_evaluated": 4,
        "response": "Block the Dover Strait",
        "immediate_loss_pct": 23.9,
        "future_loss_pct": 31.1,
        "average_loss_pct": 29.8,
        "horizon_round": 4,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 30.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 73.9,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    },
    {
      "label": "Harden port GBFXT",
      "cost": 3,
      "ready_round": 3,
      "planning": {
        "branches_evaluated": 4,
        "response": "Block the Dover Strait",
        "immediate_loss_pct": 23.9,
        "future_loss_pct": 36.4,
        "average_loss_pct": 31.6,
        "horizon_round": 4,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 0.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 73.9,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1023 → 1024
Timing: LLM 0 ms; DB 539.0 ms
Fallback: no
Map arcs: 0

## 10. Round 3 · RED

Block the Dover Strait

Rationale: Blocking the Dover Strait will significantly disrupt shipping routes, causing a substantial increase in capability loss and affecting multiple missions.

```json
[
  {
    "action": "block_chokepoint",
    "args": {
      "waypoint_id": "DOVER_STRAIT"
    }
  }
]
```

Loss: 34.5% total; 34.5 points vs base
Deep network: 46.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 4,
  "budget_total": 14,
  "pending": [
    {
      "cost": 5,
      "due": 4,
      "step": {
        "action": "replace_facility",
        "args": {
          "facility_id": "FAC04229"
        }
      }
    }
  ],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 75.5,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 3,
  "event_active": false,
  "cost": 0,
  "ready_round": 3,
  "cumulative_loss": 59.2,
  "planning": {
    "branches_evaluated": 4,
    "response": "Harden facility FAC04299",
    "immediate_loss_pct": 34.5,
    "future_loss_pct": 31.4,
    "average_loss_pct": 32.9,
    "horizon_round": 5,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 28.3,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 73.9,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 65.0,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "CHN export controls on MAT00017",
      "cost": 0,
      "ready_round": 3,
      "planning": {
        "branches_evaluated": 4,
        "response": "Harden port GBFXT",
        "immediate_loss_pct": 24.7,
        "future_loss_pct": 23.7,
        "average_loss_pct": 24.2,
        "horizon_round": 5,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 30.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 80.5,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 80.5,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1024 → 1033
Timing: LLM 5799.3 ms; DB 29186.7 ms
Fallback: no
Map targets: Dover Strait (other, 51.0, 1.45)
Map arcs: 70

## 11. Round 3 · BLUE

Harden facility FAC04299 (Varro Westmark Defence Systems S.p.A. - Rome)

Rationale: Hardening FAC04299 prevents a significant potential loss and protects a critical node in the supply chain.

```json
[
  {
    "action": "game_order",
    "args": {
      "action": "harden",
      "args": {
        "facility_id": "FAC04299"
      }
    }
  }
]
```

Loss: 34.5% total; 34.5 points vs base
Deep network: 46.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [
    {
      "cost": 5,
      "due": 4,
      "step": {
        "action": "replace_facility",
        "args": {
          "facility_id": "FAC04229"
        }
      }
    },
    {
      "cost": 3,
      "due": 4,
      "step": {
        "action": "harden",
        "args": {
          "facility_id": "FAC04299"
        }
      }
    }
  ],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 75.5,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 3,
  "event_active": false,
  "cost": 3,
  "ready_round": 4,
  "cumulative_loss": 76.5,
  "planning": {
    "branches_evaluated": 4,
    "response": "Close port GBFXT",
    "immediate_loss_pct": 34.5,
    "future_loss_pct": 33.5,
    "average_loss_pct": 33.8,
    "horizon_round": 5,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 28.3,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 70.6,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 65.0,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "Reroute exports away from port FIHEL",
      "cost": 2,
      "ready_round": 3,
      "planning": {
        "branches_evaluated": 4,
        "response": "Close port GBFXT",
        "immediate_loss_pct": 34.2,
        "future_loss_pct": 35.6,
        "average_loss_pct": 35.1,
        "horizon_round": 5,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 20.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 56.5,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1033 → 1042
Timing: LLM 5302.7 ms; DB 24604.7 ms
Fallback: no
Map targets: Varro Westmark Defence Systems S.p.A. - Rome (facility, 41.866319, 12.55338)
Map arcs: 0

## 12. Round 3 · INJECT

Event: export capacity reduced 20% for two rounds; Ready: replace_facility {'facility_id': 'FAC04229'}; Ready: harden {'facility_id': 'FAC04299'}

Rationale: Event: export capacity reduced 20% for two rounds; Ready: replace_facility {'facility_id': 'FAC04229'}; Ready: harden {'facility_id': 'FAC04299'}

```json
[
  {
    "action": "game_tick",
    "args": {
      "round": 4
    }
  }
]
```

Loss: 31.4% total; 31.4 points vs base
Deep network: 41.8%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [
    "Event: export capacity reduced 20% for two rounds",
    "Ready: replace_facility {'facility_id': 'FAC04229'}",
    "Ready: harden {'facility_id': 'FAC04299'}"
  ],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 28.3,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 73.9,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 4,
  "event_active": true,
  "cost": 0,
  "ready_round": 3,
  "cumulative_loss": 76.5,
  "planning": null,
  "alternatives": [
    {
      "label": "Harden facility FAC04299",
      "cost": 3,
      "ready_round": 4,
      "planning": {
        "branches_evaluated": 4,
        "response": "Close port GBFXT",
        "immediate_loss_pct": 34.5,
        "future_loss_pct": 33.5,
        "average_loss_pct": 33.8,
        "horizon_round": 5,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 28.3,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    },
    {
      "label": "Reroute exports away from port FIHEL",
      "cost": 2,
      "ready_round": 3,
      "planning": {
        "branches_evaluated": 4,
        "response": "Close port GBFXT",
        "immediate_loss_pct": 34.2,
        "future_loss_pct": 35.6,
        "average_loss_pct": 35.1,
        "horizon_round": 5,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 20.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 56.5,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1042 → 1043
Timing: LLM 0 ms; DB 669.4 ms
Fallback: no
Map targets: Dunmore Components Inc. - Boston (facility, 42.3267, -71.087207); Upland Components Inc. - Pittsburgh (facility, 40.419484, -79.981338); Dunmore Components Inc. - Pittsburgh (facility, 40.474836, -79.985574); Brenna Draco Components Inc. - San Diego (facility, 32.697034, -117.194384); Ostrand Components Inc. - Pittsburgh (facility, 40.445337, -79.973276); Arkon-Triton Components Inc. - Huntsville (facility, 34.701744, -86.535237); Thornbury Components Inc. - Dallas (facility, 32.780099, -96.810581); Borealis Components Inc. - Wichita (facility, 37.721936, -97.380121); Hydra Components Inc. - Huntsville (facility, 34.682, -86.591021); Volans Components Inc. - Pittsburgh (facility, 40.440587, -80.037479); Vela Sorrel Components Inc. - Pittsburgh (facility, 40.471646, -79.987208); Pavo Lumen Components Inc. - San Diego (facility, 32.756913, -117.11831); Pavo Ulvane Components Inc. - Pittsburgh (facility, 40.422962, -79.96205); Zephra Components Inc. - Huntsville (facility, 34.715168, -86.576492); Eridan Triton Components Inc. - Dallas (facility, 32.81153, -96.748281); Mensa Meridian Components Inc. - Dallas (facility, 32.73957, -96.811547); Calder Components Inc. - Dallas (facility, 32.758644, -96.849511); Granit Components Inc. - Boston (facility, 42.331346, -71.080916); Kaida Components Co., Ltd. - Dallas (facility, 32.740824, -96.763203); Triton Components Inc. - Phoenix (facility, 33.407475, -112.105179); Mensa Components Inc. - Dallas (facility, 32.803411, -96.85144); Orion Grus Components Inc. - Wichita (facility, 37.645698, -97.307374); Helion Penrose Components Inc. - San Diego (facility, 32.667254, -117.157435); Upland Kingsbridge Components Inc. - Tucson (facility, 32.206072, -110.991423); Upland Kingsbridge Components Inc. - Huntsville (facility, 34.712123, -86.610035); Calder-Draco Components Inc. - Pittsburgh (facility, 40.4395, -79.977194); Ironvale Components Inc. - Boston (facility, 42.360018, -71.07323); Kaiyang Components Corp. - Pittsburgh (facility, 40.435584, -79.974455); Granit Components Inc. - Huntsville (facility, 34.750313, -86.588407); Orrin-Cygnet Components Ltd. - Boston (facility, 42.348039, -71.122024)
Map arcs: 21

## 13. Round 4 · RED

Close port GBFXT (Port of Felixstowe)

Rationale: Closing Port of Felixstowe will disrupt 205 exporters and add 2.8% to the current loss, which is the highest immediate gain available.

```json
[
  {
    "action": "close_port",
    "args": {
      "port_id": "GBFXT"
    }
  }
]
```

Loss: 33.5% total; 33.5 points vs base
Deep network: 44.7%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [
    "Event: export capacity reduced 20% for two rounds",
    "Ready: replace_facility {'facility_id': 'FAC04229'}",
    "Ready: harden {'facility_id': 'FAC04299'}"
  ],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 28.3,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 4,
  "event_active": true,
  "cost": 0,
  "ready_round": 4,
  "cumulative_loss": 93.2,
  "planning": {
    "branches_evaluated": 3,
    "response": "none",
    "immediate_loss_pct": 33.5,
    "future_loss_pct": 32.6,
    "average_loss_pct": 33.2,
    "horizon_round": 6,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 28.3,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 70.6,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 65.0,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "CHN export controls on MAT00017",
      "cost": 0,
      "ready_round": 4,
      "planning": {
        "branches_evaluated": 3,
        "response": "none",
        "immediate_loss_pct": 31.4,
        "future_loss_pct": 29.5,
        "average_loss_pct": 30.7,
        "horizon_round": 6,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 28.3,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 75.5,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1043 → 1050
Timing: LLM 7244.7 ms; DB 7739.9 ms
Fallback: no
Map targets: Port of Felixstowe (port, 51.95, 1.32)
Map arcs: 55

## 14. Round 4 · BLUE

Conserve credits and await scheduled recovery

Rationale: Automatic wait: no affordable measure can complete within the match horizon.

```json
[
  {
    "action": "game_order",
    "args": {
      "action": "wait",
      "args": {}
    }
  }
]
```

Loss: 33.5% total; 33.5 points vs base
Deep network: 44.7%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [
    "Event: export capacity reduced 20% for two rounds",
    "Ready: replace_facility {'facility_id': 'FAC04229'}",
    "Ready: harden {'facility_id': 'FAC04299'}"
  ],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 28.3,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 4,
  "event_active": true,
  "cost": 0,
  "ready_round": 4,
  "cumulative_loss": 110.0,
  "planning": null,
  "alternatives": []
}
```
Branch: 1050 → 1051
Timing: LLM 0 ms; DB 5895.5 ms
Fallback: no
Map arcs: 0

## 15. Round 4 · INJECT

Round 5: recovery clock advanced

Rationale: Round 5: recovery clock advanced

```json
[
  {
    "action": "game_tick",
    "args": {
      "round": 5
    }
  }
]
```

Loss: 33.5% total; 33.5 points vs base
Deep network: 44.7%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 28.3,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 5,
  "event_active": true,
  "cost": 0,
  "ready_round": 4,
  "cumulative_loss": 110.0,
  "planning": null,
  "alternatives": []
}
```
Branch: 1051 → 1052
Timing: LLM 0 ms; DB 977.7 ms
Fallback: no
Map arcs: 0

## 16. Round 5 · RED

Outage at facility FAC04290 (Hydra Defence Systems S.p.A. - Genoa)

Rationale: Targeting Hydra Defence Systems S.p.A. - Genoa will significantly disrupt the supply chain due to its single point of failure status, adding meaningful loss and pressure on the network.

```json
[
  {
    "action": "facility_outage",
    "args": {
      "facility_id": "FAC04290"
    }
  }
]
```

Loss: 39.1% total; 39.1 points vs base
Deep network: 52.2%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 5,
  "event_active": true,
  "cost": 0,
  "ready_round": 5,
  "cumulative_loss": 129.6,
  "planning": {
    "branches_evaluated": 2,
    "response": "none",
    "immediate_loss_pct": 39.1,
    "future_loss_pct": 38.3,
    "average_loss_pct": 38.7,
    "horizon_round": 6,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 0.0,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 70.6,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 65.0,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "CHN export controls on MAT00017",
      "cost": 0,
      "ready_round": 5,
      "planning": {
        "branches_evaluated": 2,
        "response": "none",
        "immediate_loss_pct": 33.5,
        "future_loss_pct": 32.6,
        "average_loss_pct": 33.0,
        "horizon_round": 6,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 28.3,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1052 → 1057
Timing: LLM 4840.0 ms; DB 7109.6 ms
Fallback: no
Map targets: Hydra Defence Systems S.p.A. - Genoa (facility, 44.446463, 8.945102)
Map arcs: 1

## 17. Round 5 · BLUE

Conserve credits and await scheduled recovery

Rationale: Automatic wait: no affordable measure can complete within the match horizon.

```json
[
  {
    "action": "game_order",
    "args": {
      "action": "wait",
      "args": {}
    }
  }
]
```

Loss: 39.1% total; 39.1 points vs base
Deep network: 52.2%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 5,
  "event_active": true,
  "cost": 0,
  "ready_round": 5,
  "cumulative_loss": 149.1,
  "planning": null,
  "alternatives": []
}
```
Branch: 1057 → 1058
Timing: LLM 0 ms; DB 6930.2 ms
Fallback: no
Map arcs: 0

## 18. Round 5 · INJECT

Round 6: recovery clock advanced

Rationale: Round 6: recovery clock advanced

```json
[
  {
    "action": "game_tick",
    "args": {
      "round": 6
    }
  }
]
```

Loss: 38.3% total; 38.3 points vs base
Deep network: 51.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 6,
  "event_active": false,
  "cost": 0,
  "ready_round": 5,
  "cumulative_loss": 149.1,
  "planning": null,
  "alternatives": []
}
```
Branch: 1058 → 1059
Timing: LLM 0 ms; DB 738.5 ms
Fallback: no
Map targets: Dunmore Components Inc. - Boston (facility, 42.3267, -71.087207); Upland Components Inc. - Pittsburgh (facility, 40.419484, -79.981338); Dunmore Components Inc. - Pittsburgh (facility, 40.474836, -79.985574); Brenna Draco Components Inc. - San Diego (facility, 32.697034, -117.194384); Ostrand Components Inc. - Pittsburgh (facility, 40.445337, -79.973276); Arkon-Triton Components Inc. - Huntsville (facility, 34.701744, -86.535237); Thornbury Components Inc. - Dallas (facility, 32.780099, -96.810581); Borealis Components Inc. - Wichita (facility, 37.721936, -97.380121); Hydra Components Inc. - Huntsville (facility, 34.682, -86.591021); Volans Components Inc. - Pittsburgh (facility, 40.440587, -80.037479); Vela Sorrel Components Inc. - Pittsburgh (facility, 40.471646, -79.987208); Pavo Lumen Components Inc. - San Diego (facility, 32.756913, -117.11831); Pavo Ulvane Components Inc. - Pittsburgh (facility, 40.422962, -79.96205); Zephra Components Inc. - Huntsville (facility, 34.715168, -86.576492); Eridan Triton Components Inc. - Dallas (facility, 32.81153, -96.748281); Mensa Meridian Components Inc. - Dallas (facility, 32.73957, -96.811547); Calder Components Inc. - Dallas (facility, 32.758644, -96.849511); Granit Components Inc. - Boston (facility, 42.331346, -71.080916); Kaida Components Co., Ltd. - Dallas (facility, 32.740824, -96.763203); Triton Components Inc. - Phoenix (facility, 33.407475, -112.105179); Mensa Components Inc. - Dallas (facility, 32.803411, -96.85144); Orion Grus Components Inc. - Wichita (facility, 37.645698, -97.307374); Helion Penrose Components Inc. - San Diego (facility, 32.667254, -117.157435); Upland Kingsbridge Components Inc. - Tucson (facility, 32.206072, -110.991423); Upland Kingsbridge Components Inc. - Huntsville (facility, 34.712123, -86.610035); Calder-Draco Components Inc. - Pittsburgh (facility, 40.4395, -79.977194); Ironvale Components Inc. - Boston (facility, 42.360018, -71.07323); Kaiyang Components Corp. - Pittsburgh (facility, 40.435584, -79.974455); Granit Components Inc. - Huntsville (facility, 34.750313, -86.588407); Orrin-Cygnet Components Ltd. - Boston (facility, 42.348039, -71.122024)
Map arcs: 16

## 19. Round 6 · RED

Block the Panama Canal

Rationale: Blocking the Panama Canal will disrupt key shipping routes and add significant loss, as it is a critical chokepoint for global trade.

```json
[
  {
    "action": "block_chokepoint",
    "args": {
      "waypoint_id": "PANAMA_CANAL"
    }
  }
]
```

Loss: 39.0% total; 39.0 points vs base
Deep network: 52.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 6,
  "event_active": false,
  "cost": 0,
  "ready_round": 6,
  "cumulative_loss": 168.6,
  "planning": {
    "branches_evaluated": 1,
    "response": "none",
    "immediate_loss_pct": 39.0,
    "future_loss_pct": 39.0,
    "average_loss_pct": 39.0,
    "horizon_round": 6,
    "missions": [
      {
        "item_id": "PLT00003",
        "name": "FPV strike drone FSD-13A",
        "capability_pct": 0.0,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00014",
        "name": "Cruise missile CM-72B",
        "capability_pct": 70.6,
        "threshold_pct": 80
      },
      {
        "item_id": "PLT00035",
        "name": "Unmanned surface vessel USV-81A",
        "capability_pct": 65.0,
        "threshold_pct": 80
      }
    ]
  },
  "alternatives": [
    {
      "label": "CHN export controls on MAT00017",
      "cost": 0,
      "ready_round": 6,
      "planning": {
        "branches_evaluated": 1,
        "response": "none",
        "immediate_loss_pct": 38.3,
        "future_loss_pct": 38.3,
        "average_loss_pct": 38.3,
        "horizon_round": 6,
        "missions": [
          {
            "item_id": "PLT00003",
            "name": "FPV strike drone FSD-13A",
            "capability_pct": 0.0,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00014",
            "name": "Cruise missile CM-72B",
            "capability_pct": 70.6,
            "threshold_pct": 80
          },
          {
            "item_id": "PLT00035",
            "name": "Unmanned surface vessel USV-81A",
            "capability_pct": 65.0,
            "threshold_pct": 80
          }
        ]
      }
    }
  ]
}
```
Branch: 1059 → 1062
Timing: LLM 4547.4 ms; DB 5555.5 ms
Fallback: no
Map targets: Panama Canal (other, 9.1, -79.7)
Map arcs: 49

## 20. Round 6 · BLUE

Conserve credits and await scheduled recovery

Rationale: Automatic wait: no affordable measure can complete within the match horizon.

```json
[
  {
    "action": "game_order",
    "args": {
      "action": "wait",
      "args": {}
    }
  }
]
```

Loss: 39.0% total; 39.0 points vs base
Deep network: 52.0%; parts layer: 0.0%
Exercise state and compared plans:
```json
{
  "budget_remaining": 1,
  "budget_total": 14,
  "pending": [],
  "completed": [],
  "missions": [
    {
      "item_id": "PLT00003",
      "name": "FPV strike drone FSD-13A",
      "capability_pct": 0.0,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00014",
      "name": "Cruise missile CM-72B",
      "capability_pct": 70.6,
      "threshold_pct": 80
    },
    {
      "item_id": "PLT00035",
      "name": "Unmanned surface vessel USV-81A",
      "capability_pct": 65.0,
      "threshold_pct": 80
    }
  ],
  "round": 6,
  "event_active": false,
  "cost": 0,
  "ready_round": 6,
  "cumulative_loss": 188.1,
  "planning": null,
  "alternatives": []
}
```
Branch: 1062 → 1063
Timing: LLM 0 ms; DB 6181.1 ms
Fallback: no
Map arcs: 0
