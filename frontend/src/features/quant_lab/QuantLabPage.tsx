import { ChartNoAxesCombined } from 'lucide-react';

import { ReservedModule } from '../../components/ReservedModule';

export function QuantLabPage() {
  return (
    <ReservedModule
      eyebrow="Research / Quant Lab"
      title="Quant Lab"
      description="A future environment for reproducible historical research and signal evaluation."
      purpose="This boundary will support historical datasets, factor research, backtests, strategy comparison, and statistical analysis without leaking provider details into the domain."
      icon={ChartNoAxesCombined}
    />
  );
}
