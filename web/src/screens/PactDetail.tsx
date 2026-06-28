import { useParams } from "react-router-dom";
import { PactWorld } from "../components/PactWorld";

// PactDetail is a thin wrapper over PactWorld (the card-left / panel-right
// "world"). The carousel→world flip-open entry lives in PactWorld itself.
export function PactDetail() {
  const { pactId } = useParams();
  return <PactWorld pactId={pactId!} />;
}
