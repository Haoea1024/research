import { forwardRef } from "react";
import { BlockPane, type BlockPaneHandle, type BlockPaneProps } from "./BlockPane";

export const StructuredBlockView = forwardRef<BlockPaneHandle, BlockPaneProps>(function StructuredBlockView(props, ref) {
  return <BlockPane {...props} ref={ref} />;
});
