import { useParams } from "react-router-dom";
import { PactWorld } from "../components/PactWorld";

// PactDetail is now a thin standalone-mode wrapper over PactWorld (the card-left /
// panel-right "world"). The overlay mode + carousel→world flip live in Task 8.
export function PactDetail() {
  const { pactId } = useParams();
  return <PactWorld pactId={pactId!} mode="standalone" />;
}
