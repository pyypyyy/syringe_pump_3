from dataclasses import dataclass


@dataclass
class FlowCalibrationTrial:
    trial_id: str
    gas: str
    target_flow_lpm: float
    repeat_index: int
    stroke_start_ml: float
    stroke_end_ml: float


class CalibrationPlan:
    @staticmethod
    def build(gas, flows_lpm, repeats, stroke_start_ml, stroke_end_ml):
        trials = []
        for flow in flows_lpm:
            for rep in range(1, repeats + 1):
                trials.append(
                    FlowCalibrationTrial(
                        trial_id=f"{gas}_{flow:0.3f}_LPM_rep{rep}",
                        gas=gas,
                        target_flow_lpm=float(flow),
                        repeat_index=rep,
                        stroke_start_ml=float(stroke_start_ml),
                        stroke_end_ml=float(stroke_end_ml),
                    )
                )
        return trials
