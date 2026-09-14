import { ChartNoAxesCombined } from 'lucide-react';

import { ReservedModule } from '../../components/ReservedModule';

export function QuantLabPage() {
  return (
    <ReservedModule
      eyebrow="研究 / 量化实验室"
      title="量化实验室"
      description="未来用于开展可复现的历史研究和信号评估。"
      purpose="该模块将支持历史数据集、因子研究、回测、策略比较和统计分析，同时保持数据供应商细节与业务领域隔离。"
      icon={ChartNoAxesCombined}
    />
  );
}
