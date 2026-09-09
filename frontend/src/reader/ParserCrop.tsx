import { useEffect, useState } from "react";

interface Props { imageUrl: string | null | undefined; alt: string; kind: "Figure" | "Table"; }

export function ParserCrop({ imageUrl, alt, kind }: Props) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [imageUrl]);
  if (!imageUrl || failed) return <div className="layout-media-placeholder">{kind} crop unavailable</div>;
  return <img loading="lazy" src={imageUrl} alt={alt} onError={() => setFailed(true)} />;
}
