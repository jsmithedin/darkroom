import { RecentRolls } from "../components/RecentRolls";
import { RollForm } from "../components/RollForm";

export function LogRoll() {
  return (
    <>
      <h1>Log a roll</h1>
      <div className="notebook">
        <RollForm />
        <RecentRolls />
      </div>
    </>
  );
}
