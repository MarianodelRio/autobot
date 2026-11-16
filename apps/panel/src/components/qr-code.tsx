import { QRCodeCanvas, QRCodeSVG } from "qrcode.react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const SIZE = 140;
const PRINT_SIZE = 320;
const EXPORT_SIZE = 512;
// The standard quiet zone (4 modules) keeps a printed or scanned code readable.
const MARGIN = 4;

function triggerDownload(fileName: string, href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = fileName;
  a.click();
}

/** A QR code with a correct size and margin (C13), downloadable as SVG or PNG, and
 * a larger view meant for printing. Used for a channel's public link and for the
 * owner's invite link (C14). */
export function QrCode({
  value,
  title,
  fileName,
}: {
  value: string;
  title: string;
  fileName: string;
}) {
  const [printOpen, setPrintOpen] = useState(false);
  const exportCanvas = useRef<HTMLCanvasElement>(null);
  const svgId = `qr-svg-${fileName}`;

  function downloadSvg() {
    const svg = document.getElementById(svgId);
    if (!svg) return;
    const markup = new XMLSerializer().serializeToString(svg);
    const url = URL.createObjectURL(
      new Blob([markup], { type: "image/svg+xml" }),
    );
    triggerDownload(`${fileName}.svg`, url);
    URL.revokeObjectURL(url);
  }

  function downloadPng() {
    const canvas = exportCanvas.current;
    if (!canvas) return;
    triggerDownload(`${fileName}.png`, canvas.toDataURL("image/png"));
  }

  return (
    <div className="space-y-2">
      <div className="inline-block border bg-white p-2">
        <QRCodeSVG
          id={svgId}
          value={value}
          size={SIZE}
          marginSize={MARGIN}
          title={title}
        />
      </div>
      {/* Off-screen, higher-resolution canvas used only to export the PNG. */}
      <QRCodeCanvas
        ref={exportCanvas}
        value={value}
        size={EXPORT_SIZE}
        marginSize={MARGIN}
        className="hidden"
        aria-hidden="true"
      />
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={downloadSvg}>
          Descargar SVG
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={downloadPng}>
          Descargar PNG
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setPrintOpen(true)}
        >
          Ver para imprimir
        </Button>
      </div>
      <Dialog open={printOpen} onOpenChange={setPrintOpen}>
        <DialogContent className="print:border-none print:shadow-none">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>
          <div className="flex justify-center bg-white p-6">
            <QRCodeSVG
              value={value}
              size={PRINT_SIZE}
              marginSize={MARGIN}
              title={title}
            />
          </div>
          <Button type="button" onClick={() => window.print()}>
            Imprimir
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
