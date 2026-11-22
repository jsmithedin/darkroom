import { Link } from "react-router-dom";
import { insufficientStock } from "../api/stock";

/** An error from a write. A refused stock write also offers to record a purchase or a recount. */
export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const short = insufficientStock(error);
  return (
    <div role="alert" className="error">
      <p>{message}</p>
      {short && (
        <p className="row">
          <Link
            className="button"
            to={`/stock?recount=${short.film_id}:${short.format_id}`}
          >
            Record a recount
          </Link>
          <Link
            className="button"
            to={`/purchases?film=${short.film_id}&format=${short.format_id}`}
          >
            Record a purchase
          </Link>
        </p>
      )}
    </div>
  );
}
