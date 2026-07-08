import { SettingsForm } from "@/components/SettingsForm";
import { PageHeader } from "@/components/ui/PageHeader";

export function SettingsPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Configurações"
        description="Parâmetros do bot em data/settings.json — hot-reload no próximo ciclo."
      />
      <SettingsForm />
    </div>
  );
}
