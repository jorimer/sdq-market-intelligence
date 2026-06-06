import { PageHead, StateBlock } from "./primitives";

/** Honest placeholder for axes/tools whose dedicated UI is not built yet. */
export function PlaceholderPage({
  eyebrow,
  title,
  sub,
  api,
}: {
  eyebrow?: string;
  title: string;
  sub?: string;
  api?: string;
}) {
  return (
    <div>
      <PageHead eyebrow={eyebrow} title={title} sub={sub} />
      <StateBlock
        kind="soon"
        message={
          api
            ? `La interfaz de este eje está en construcción. El backend ya expone ${api}.`
            : "Esta sección está en construcción."
        }
      />
    </div>
  );
}
