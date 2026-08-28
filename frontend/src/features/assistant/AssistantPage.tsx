import { Bot } from 'lucide-react';

import { ReservedModule } from '../../components/ReservedModule';

export function AssistantPage() {
  return (
    <ReservedModule
      eyebrow="AI / Research Assistant"
      title="AI Research Assistant"
      description="A future assistant grounded in the platform's own research outputs—not a disconnected generic chatbot."
      purpose="This boundary will consume versioned artifacts from Tail Radar, Intelligence, and Quant Lab. Model access and secrets will remain entirely in the backend."
      icon={Bot}
    />
  );
}
