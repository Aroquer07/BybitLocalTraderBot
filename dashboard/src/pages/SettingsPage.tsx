import { SettingsForm } from "@/components/SettingsForm";



export function SettingsPage() {

  return (

    <div className="space-y-6">

      <div>

        <h1 className="text-2xl font-bold text-white">Configurações</h1>

        <p className="mt-1 text-sm text-slate-400">

          Edite data/settings.json com formulário organizado (hot-reload)

        </p>

      </div>

      <SettingsForm />

    </div>

  );

}

