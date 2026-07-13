#include "exposurerender.h"
#include <iostream>

extern "C" {
    EXPOSURE_RENDER_DLL void* er_create_tracer() {
        try {
            return new ExposureRender::ErTracer();
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in create_tracer: " << e.Message << std::endl;
            return nullptr;
        } catch (...) {
            return nullptr;
        }
    }

    EXPOSURE_RENDER_DLL void* er_create_light() {
        try {
            return new ExposureRender::ErLight();
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in create_light: " << e.Message << std::endl;
            return nullptr;
        }
    }
    
    EXPOSURE_RENDER_DLL void er_destroy_light(void* light) {
        delete static_cast<ExposureRender::ErLight*>(light);
    }
    
    EXPOSURE_RENDER_DLL void er_bind_light(void* light) {
        try {
            ExposureRender::BindLight(*static_cast<ExposureRender::ErLight*>(light));
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in bind_light: " << e.Message << std::endl;
        }
    }

    EXPOSURE_RENDER_DLL void er_tracer_add_light(void* tracer, void* light) {
        auto t = static_cast<ExposureRender::ErTracer*>(tracer);
        auto l = static_cast<ExposureRender::ErLight*>(light);
        if (t->LightIDs.Count < 256) {
            t->LightIDs[t->LightIDs.Count] = l->ID;
            t->LightIDs.Count++;
        }
    }

    EXPOSURE_RENDER_DLL void er_tracer_clear_lights(void* tracer) {
        auto t = static_cast<ExposureRender::ErTracer*>(tracer);
        t->LightIDs.Count = 0;
    }

    EXPOSURE_RENDER_DLL void er_set_light_properties(void* light, 
        float posX, float posY, float posZ,
        float dirX, float dirY, float dirZ,
        float colorR, float colorG, float colorB, float multiplier,
        float sizeX, float sizeY) 
    {
        auto l = static_cast<ExposureRender::ErLight*>(light);
        l->Multiplier = multiplier;
        
        // Setup shape (Plane light)
        l->Shape.Type = ExposureRender::Enums::Plane; // Plane
        l->Shape.OneSided = true;
        l->Shape.Size = ExposureRender::Vec3f(sizeX, sizeY, 1.0f);
        
        // Default area light logic:
        ExposureRender::Vec3f P(posX, posY, posZ);
        ExposureRender::Vec3f N(dirX, dirY, dirZ);
        N = ExposureRender::Normalize(N);
        
        // Create coordinate frame
        ExposureRender::Vec3f U, V;
        if (fabs(N[0]) > fabs(N[1])) {
            float invLen = 1.0f / sqrt(N[0]*N[0] + N[2]*N[2]);
            U = ExposureRender::Vec3f(-N[2]*invLen, 0.0f, N[0]*invLen);
        } else {
            float invLen = 1.0f / sqrt(N[1]*N[1] + N[2]*N[2]);
            U = ExposureRender::Vec3f(0.0f, N[2]*invLen, -N[1]*invLen);
        }
        V = ExposureRender::Cross(N, U);
        
        // Transform Matrix
        for(int i=0; i<3; i++) {
            l->Shape.TM.NN[i][0] = U[i];
            l->Shape.TM.NN[i][1] = V[i];
            l->Shape.TM.NN[i][2] = N[i];
            l->Shape.TM.NN[i][3] = P[i];
        }
        l->Shape.TM.NN[3][0] = 0.0f; l->Shape.TM.NN[3][1] = 0.0f; l->Shape.TM.NN[3][2] = 0.0f; l->Shape.TM.NN[3][3] = 1.0f;
        
        l->Shape.Update();
    }
    
    EXPOSURE_RENDER_DLL void er_destroy_tracer(void* tracer) {
        delete static_cast<ExposureRender::ErTracer*>(tracer);
    }

    EXPOSURE_RENDER_DLL void er_set_tracer_resolution(void* tracer, int w, int h) {
        try {
            auto t = static_cast<ExposureRender::ErTracer*>(tracer);
            t->Camera.FilmSize[0] = w;
            t->Camera.FilmSize[1] = h;
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in set_tracer_resolution: " << e.Message << std::endl;
        }
    }
    
    EXPOSURE_RENDER_DLL void er_bind_tracer(void* tracer) {
        try {
            ExposureRender::BindTracer(*static_cast<ExposureRender::ErTracer*>(tracer));
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in bind_tracer: " << e.Message << std::endl;
        }
    }

    EXPOSURE_RENDER_DLL int er_get_tracer_id(void* tracer) {
        return static_cast<ExposureRender::ErTracer*>(tracer)->ID;
    }

    EXPOSURE_RENDER_DLL void er_set_camera(void* tracer, 
        float posX, float posY, float posZ,
        float targetX, float targetY, float targetZ,
        float upX, float upY, float upZ,
        float fov, float clipNear, float clipFar,
        float exposure, float gamma) 
    {
        try {
            auto t = static_cast<ExposureRender::ErTracer*>(tracer);
            t->Camera.Pos = ExposureRender::Vec3f(posX, posY, posZ);
            t->Camera.Target = ExposureRender::Vec3f(targetX, targetY, targetZ);
            t->Camera.Up = ExposureRender::Vec3f(upX, upY, upZ);
            t->Camera.FOV = fov;
            t->Camera.ClipNear = clipNear;
            t->Camera.ClipFar = clipFar;
            t->Camera.Exposure = exposure;
            t->Camera.Gamma = gamma;
            t->Camera.Update();
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in set_camera: " << e.Message << std::endl;
        }
    }

    EXPOSURE_RENDER_DLL void er_clear_opacity_tf(void* tracer) {
        auto t = static_cast<ExposureRender::ErTracer*>(tracer);
        t->Opacity1D.Clear();
    }

    EXPOSURE_RENDER_DLL void er_add_opacity_node(void* tracer, float position, float value) {
        auto t = static_cast<ExposureRender::ErTracer*>(tracer);
        t->Opacity1D.AddNode(ExposureRender::ScalarNode(position, value));
    }

    EXPOSURE_RENDER_DLL void er_clear_diffuse_tf(void* tracer) {
        auto t = static_cast<ExposureRender::ErTracer*>(tracer);
        t->Diffuse1D.Clear();
    }

    EXPOSURE_RENDER_DLL void er_add_diffuse_node(void* tracer, float position, float r, float g, float b) {
        auto t = static_cast<ExposureRender::ErTracer*>(tracer);
        ExposureRender::ColorNode node;
        node.ScalarNodes[0] = ExposureRender::ScalarNode(position, r);
        node.ScalarNodes[1] = ExposureRender::ScalarNode(position, g);
        node.ScalarNodes[2] = ExposureRender::ScalarNode(position, b);
        t->Diffuse1D.AddNode(node);
    }

    EXPOSURE_RENDER_DLL void* er_create_volume() {
        try {
            return new ExposureRender::ErVolume();
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in create_volume: " << e.Message << std::endl;
            return nullptr;
        }
    }
    
    EXPOSURE_RENDER_DLL void er_destroy_volume(void* vol) {
        delete static_cast<ExposureRender::ErVolume*>(vol);
    }
    
    EXPOSURE_RENDER_DLL void er_bind_volume_data(void* vol, int dimX, int dimY, int dimZ, float spX, float spY, float spZ, unsigned short* data) {
        try {
            auto v = static_cast<ExposureRender::ErVolume*>(vol);
            ExposureRender::Vec3i res(dimX, dimY, dimZ);
            ExposureRender::Vec3f sp(spX, spY, spZ);
            v->BindVoxels(res, sp, data, true);
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in bind_volume_data: " << e.Message << std::endl;
        }
    }
    
    EXPOSURE_RENDER_DLL void er_bind_volume(void* vol) {
        try {
            ExposureRender::BindVolume(*static_cast<ExposureRender::ErVolume*>(vol));
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in bind_volume: " << e.Message << std::endl;
        }
    }
    
    EXPOSURE_RENDER_DLL void er_render_estimate(int tracerID) {
        try {
            ExposureRender::RenderEstimate(tracerID);
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in render_estimate: " << e.Message << std::endl;
        }
    }
    
    EXPOSURE_RENDER_DLL void er_get_estimate(int tracerID, unsigned char* pData) {
        try {
            ExposureRender::GetEstimate(tracerID, pData);
        } catch (const ExposureRender::Exception& e) {
            std::cerr << "ER Exception in get_estimate: " << e.Message << std::endl;
        }
    }

    EXPOSURE_RENDER_DLL void er_reset_accumulation(void* tracer) {
        auto t = static_cast<ExposureRender::ErTracer*>(tracer);
        t->NoIterations = 0;
    }
}
