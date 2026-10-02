import { setOps, useOps } from "../state/store";
import { BranchSwitcher } from "./BranchSwitcher";
import { DiffPanel } from "./DiffPanel";
import { TimeSlider } from "./TimeSlider";

export function BottomBar() {
  const diffOpen = useOps((s) => s.diffOpen);
  return (
    <footer className="bottombar glass">
      <BranchSwitcher />
      <TimeSlider />
      <button
        type="button"
        className={`btn btn--quiet bottombar__diff${diffOpen ? " is-on" : ""}`}
        aria-pressed={diffOpen}
        onClick={() => setOps({ diffOpen: !diffOpen })}
      >
        Diff
      </button>
      <DiffPanel />
    </footer>
  );
}
