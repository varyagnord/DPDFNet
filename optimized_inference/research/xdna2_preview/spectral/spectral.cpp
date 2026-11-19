#include "dpdfnet_xdna2_spectral.h"
#include "r190_host_contract_v1.h"

#include <cfenv>
#include <xmmintrin.h>
#include <unistd.h>

#if DPDFNET_XDNA2_MODEL == 2
#include "r265_spectral_engine_v1.h"
#include "r339_m2_df_bfp16_k128_backend_v1.h"
namespace selected = r339_m2_df_bfp16_k128;
#elif DPDFNET_XDNA2_MODEL == 8
#include "r313_spectral_engine_v1.h"
#include "r313_live_backend_v1.h"
namespace selected = r296;
#else
#error Unsupported DPDFNet model
#endif

namespace {
using namespace r101;

Config load(const char *name) {
    require(name && name[0] == '/', "Absolute accelerator manifest required");
    const auto path = fs::canonical(name);
    const auto manifest = Json::parse(r33::read_file(path, 4 * 1024 * 1024));
    const auto root = fs::canonical(manifest.at("root").get<std::string>());
    require(root == path.parent_path() && integer(manifest.at("version"), 1) == 1
                && manifest.at("precision") == "bf16" && manifest.at("recording") == false,
            "Incompatible accelerator manifest");
    const auto registry = manifest.at("model_registry");
    file(registry, root);
    require(fs::canonical(registry.at("path").get<std::string>())
                == root / "R190_MODEL_REGISTRY_V1.json",
            "Unexpected model registry");
    auto config = r190::config(registry.at("path").get<std::string>(), DPDFNET_XDNA2_MODEL, false);
    config.native_binding = manifest.at("candidate_binding");
    const auto native = Json::parse(file(config.native_binding, root));
    require(native.at("version") == 1 && native.at("precision") == "bf16"
                && native.at("runtime_default") == false,
            "Incompatible accelerator bindings");
#if DPDFNET_XDNA2_MODEL == 2
    require(manifest.at("kind") == "dpdfnet-private-model2-five-data-arguments-pcm-v1"
                && manifest.at("profile") == "dual-dprnn-m2-df-bfp16-k128"
                && native.at("kind") == "dpdfnet-private-model2-five-data-arguments-native-v1",
            "Incompatible model 2 profile");
    r265::set_graph(config, manifest.at("prior_graph"), manifest.at("graph_rewrite"));
#else
    const auto rewrite = manifest.at("graph_rewrite");
    const auto graph = manifest.at("lazy_graph");
    require(manifest.at("kind") == "dpdfnet-private-matched-BF16-PCM-v1"
                && manifest.at("profile") == "matched-bf16-split"
                && native.at("kind") == "dpdfnet-private-context-weights-no-host-slot-v1"
                && native.at("regime") == manifest.at("regime")
                && rewrite.at("sha256") == "c5efe18d1aef93fca7a5da796b4130218d082a16f6bc065c38170af4370b3d2b"
                && graph.at("sha256") == "bae221821c17c55b38eb7ef3d914d531db2bf639a578e6ea392c43e787be4032",
            "Incompatible model 8 profile");
    r296::set_graph(config, manifest.at("prior_graph"), rewrite);
    const auto lazy = r254::document(graph, root, "r311_lazy_state_graphs_v1/GRAPHS.json");
    const auto &row = r279::model_row(lazy.at("models"), DPDFNET_XDNA2_MODEL);
    require(lazy.at("passed") == true && row.at("retained_CPU_nodes") == 213,
            "Incompatible model 8 graph");
    config.model_bytes = file(row.at("graph"), root);
#endif
    return config;
}

void hold_if_uncertain() noexcept {
    if (r45_containment::pending_or_unknown) {
        for (;;) ::pause();
    }
}

struct Session {
    const pid_t pid = getpid();
    const std::thread::id thread = std::this_thread::get_id();
    selected::LiveBackend backend;
    SpectralEngine engine;
    uint32_t frame = 0;
    uint32_t generation = 0;
    bool failed = false;

    explicit Session(const Config &config) : backend(config, nullptr), engine(config, backend) {}
    ~Session() { hold_if_uncertain(); }

    bool owned() const noexcept { return pid == getpid() && thread == std::this_thread::get_id(); }
    void ready() const {
        require(owned() && !failed, "Invalid spectral session");
        require((_mm_getcsr() & 0xe040u) == 0 && std::fegetround() == FE_TONEAREST,
                "Invalid floating-point mode");
    }
};
} // namespace

extern "C" uint32_t dpdfnet_xdna2_spectral_abi() { return 1; }

extern "C" int dpdfnet_xdna2_spectral_validate(const char *manifest) {
    try {
        const auto config = load(manifest);
        const auto prepared = selected::Prepared::load(
            config.native_binding.at("path").get<std::string>(), DPDFNET_XDNA2_MODEL);
        const Session closed(config);
        return prepared.model == DPDFNET_XDNA2_MODEL ? 0 : -1;
    } catch (...) {
        return -1;
    }
}

extern "C" void *dpdfnet_xdna2_spectral_open(const char *manifest) {
    try {
        auto session = std::make_unique<Session>(load(manifest));
        session->ready();
        session->backend.open();
        return session.release();
    } catch (...) {
        hold_if_uncertain();
        return nullptr;
    }
}

extern "C" int dpdfnet_xdna2_spectral_step(void *opaque, const float *in, float *out) {
    auto *session = static_cast<Session *>(opaque);
    if (!session || !session->owned() || !in || !out) return -1;
    try {
        session->ready();
        require(session->frame != UINT32_MAX, "Spectral frame counter exhausted");
        std::copy_n(in, DPDFNET_XDNA2_SPECTRAL_WORDS, session->engine.input());
        session->engine.process(session->frame, session->generation);
        session->ready();
        std::copy_n(session->engine.enhanced(), DPDFNET_XDNA2_SPECTRAL_WORDS, out);
        ++session->frame;
        return 0;
    } catch (...) {
        hold_if_uncertain();
        session->failed = true;
        return -1;
    }
}

extern "C" int dpdfnet_xdna2_spectral_reset(void *opaque) {
    auto *session = static_cast<Session *>(opaque);
    if (!session || !session->owned()) return -1;
    try {
        session->ready();
        require(session->generation != UINT32_MAX, "Spectral reset counter exhausted");
        session->engine.reset();
        ++session->generation;
        return 0;
    } catch (...) {
        hold_if_uncertain();
        session->failed = true;
        return -1;
    }
}

extern "C" void dpdfnet_xdna2_spectral_close(void *opaque) {
    auto *session = static_cast<Session *>(opaque);
    if (session && session->owned()) delete session;
}
